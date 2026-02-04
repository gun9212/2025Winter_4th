"""RAG (Retrieval-Augmented Generation) API endpoints.

이 모듈은 RAG 시스템의 핵심 API 엔드포인트를 정의합니다:
- 문서 수집 (Ingestion): Celery 태스크로 비동기 처리
- 검색 (Search): 벡터 유사도 기반 검색 + LLM 답변 생성
- 문서 목록 조회
"""

import structlog
from fastapi import APIRouter, HTTPException, status
from sqlalchemy import func, select

from app.api.deps import ApiKey, DbSession
from app.models.document import Document
from app.models.embedding import DocumentChunk
from app.pipeline.step_07_embed import EmbeddingService
from app.schemas.rag_dto import (
    DocumentInfo,
    DocumentListResponse,
    IngestRequest,
    IngestResponse,
    SearchRequest,
    SearchResponse,
    SearchResult,
    SourceReference,
)
from app.services.ai.gemini import GeminiService

# Celery 태스크 import
from app.tasks.pipeline import ingest_folder as ingest_folder_task
from app.tasks.pipeline import reprocess_document as reprocess_document_task

logger = structlog.get_logger()

router = APIRouter()

# 제휴 업체 키워드 (간식/회식 관련 쿼리 시 사용)
PARTNER_KEYWORDS = {"간식", "회식", "음식", "배달", "식사", "먹", "제휴"}


@router.post(
    "/ingest/folder",
    response_model=IngestResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="폴더 수집 시작",
    description="""
    Google Drive 폴더의 문서들을 RAG 인덱싱을 위해 수집합니다.
    
    **중요 사항:**
    - `event_id`는 요청 시점에 필요하지 않음 (Ground Truth 기준)
    - Event 매핑은 Enrichment 단계에서 청크 수준으로 결정됨
    - LLM이 각 청크(안건)의 내용을 분석하여 Event를 추론
    
    **옵션:**
    - `is_privacy_sensitive`: 참조용으로만 저장 (임베딩 없음)
    - `recursive`: 하위 폴더 포함 처리
    - `file_types`: 파일 타입 필터
    - `exclude_patterns`: 제외할 파일 패턴
    
    **처리 흐름 (Celery 비동기):**
    1. Drive API로 폴더 내 파일 목록 조회
    2. 다운로드 및 처리 가능 형식으로 변환
    3. Upstage Document Parser로 파싱
    4. Parent-Child 청킹 적용
    5. 메타데이터 주입 (LLM이 청크별 Event 추론)
    6. Vertex AI text-embedding-004로 임베딩
    7. PostgreSQL + pgvector에 저장
    
    **응답 후 처리:**
    - `task_id`를 사용하여 `/api/v1/tasks/{task_id}`에서 진행 상황 조회
    """,
)
async def ingest_folder(
    request: IngestRequest,
    db: DbSession,
    api_key: ApiKey,
) -> IngestResponse:
    """
    Google Drive 폴더에서 문서를 수집합니다.
    
    7단계 RAG 파이프라인을 비동기 Celery 태스크로 실행합니다.
    Event 매핑은 수집 요청 시점이 아닌 청크 수준에서 결정됩니다.
    
    Args:
        request: 수집 요청 (folder_id, options)
        db: 데이터베이스 세션 (현재 사용 안함, 추후 확장용)
        api_key: API 키 인증
        
    Returns:
        IngestResponse: task_id를 포함한 응답
        
    Raises:
        HTTPException: Celery 연결 실패 시 503 오류
    """
    try:
        # Pydantic 모델을 dict로 변환 (Celery JSON 직렬화 필요)
        # Celery는 Pydantic 객체를 직접 전달할 수 없음
        options_dict = request.options.model_dump() if request.options else {}
        
        # Celery 태스크 비동기 실행
        # .delay()는 .apply_async()의 축약형
        task = ingest_folder_task.delay(
            drive_folder_id=request.folder_id,
            options=options_dict,
        )
        
        logger.info(
            "폴더 수집 태스크 시작됨",
            task_id=task.id,
            folder_id=request.folder_id,
            options=options_dict,
        )
        
        return IngestResponse(
            task_id=task.id,
            message="문서 수집이 시작되었습니다. Event 매핑은 청크 수준에서 결정됩니다.",
            documents_found=0,  # 실제 개수는 태스크 완료 후 확인 가능
        )
        
    except Exception as e:
        # Redis 연결 실패 등의 예외 처리
        logger.exception("Celery 태스크 시작 실패", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"비동기 작업 큐 연결 실패: {str(e)}. Redis 서버 상태를 확인하세요.",
        )


@router.post(
    "/search",
    response_model=SearchResponse,
    summary="문서 검색",
    description="""
    하이브리드 벡터 검색으로 인덱싱된 문서를 검색합니다.

    **다중 턴 대화는 `/api/v1/chat` 엔드포인트를 사용하세요.**
    이 엔드포인트는 대화 컨텍스트 없는 직접 검색용입니다.

    **검색 전략:**
    1. Vertex AI로 쿼리 임베딩
    2. Child 청크에서 벡터 유사도 검색
    3. 시간 가중치 적용
    4. access_level로 필터링
    5. Parent 콘텐츠를 컨텍스트로 반환
    """,
)
async def search_documents(
    request: SearchRequest,
    db: DbSession,
    api_key: ApiKey,
) -> SearchResponse:
    """
    RAG를 사용하여 인덱싱된 문서를 검색합니다.

    대화 컨텍스트가 포함된 검색은 /chat 엔드포인트를 사용하세요.
    """
    try:
        embedding_service = EmbeddingService(db)

        # Step 1: 쿼리 임베딩 생성
        logger.info("Generating query embedding", query=request.query[:50])
        query_embedding = await embedding_service.embed_single(request.query)

        # Step 2: 하이브리드 검색 (시맨틱 + 시간 가중치)
        logger.info("Searching with time decay", top_k=request.top_k, user_level=request.user_level)
        search_results = await embedding_service.search_with_time_decay(
            query_embedding=query_embedding,
            limit=request.top_k,
            access_level=request.user_level,
        )

        if not search_results:
            logger.info("No search results found", query=request.query[:50])
            return SearchResponse(
                query=request.query,
                results=[],
                answer="관련 문서를 찾을 수 없습니다." if request.generate_answer else None,
                sources=[],
            )

        # Step 3: 결과 변환
        results: list[SearchResult] = []
        sources: list[SourceReference] = []
        context_chunks: list[str] = []
        seen_doc_ids: set[int] = set()

        for item in search_results:
            # SearchResult 생성
            results.append(
                SearchResult(
                    document_id=item["document_id"],
                    document_name=item["document_name"],
                    chunk_content=item["content"],
                    similarity_score=item.get("final_score", item.get("semantic_score", 0.0)),
                    metadata={
                        "section_header": item.get("section_header"),
                        "semantic_score": item.get("semantic_score"),
                        "time_score": item.get("time_score"),
                    },
                )
            )

            # 중복 제거하여 SourceReference 생성
            doc_id = item["document_id"]
            if doc_id not in seen_doc_ids:
                seen_doc_ids.add(doc_id)
                sources.append(
                    SourceReference(
                        document_id=doc_id,
                        document_name=item["document_name"],
                        drive_id=item["drive_id"],
                        url=f"https://drive.google.com/file/d/{item['drive_id']}/view",
                    )
                )

            # LLM 컨텍스트용 청크 수집 (parent_content 우선 사용)
            if request.include_context and item.get("parent_content"):
                context_chunks.append(item["parent_content"])
            else:
                context_chunks.append(item["content"])

        # Step 4: LLM 답변 생성 (옵션)
        answer = None
        partner_info = None

        if request.generate_answer and context_chunks:
            # 제휴 업체 키워드 체크
            query_has_partner_keyword = any(
                keyword in request.query for keyword in PARTNER_KEYWORDS
            )
            if query_has_partner_keyword:
                # TODO: 실제 제휴 업체 정보 DB에서 조회
                partner_info = {
                    "message": "제휴 업체 정보는 별도 테이블에서 조회 필요",
                }

            logger.info("Generating LLM answer", context_count=len(context_chunks))
            gemini_service = GeminiService()
            answer = gemini_service.generate_answer(
                query=request.query,
                context=context_chunks,
            )

        logger.info(
            "Search completed",
            query=request.query[:50],
            results_count=len(results),
            answer_generated=answer is not None,
        )

        return SearchResponse(
            query=request.query,
            results=results,
            answer=answer,
            sources=sources,
            partner_info=partner_info,
        )

    except Exception as e:
        logger.exception("Search failed", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"검색 중 오류가 발생했습니다: {str(e)}",
        )


@router.post(
    "/documents/{document_id}/reprocess",
    response_model=IngestResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="문서 재처리",
    description="""
    기존 문서를 재처리합니다.
    
    지정된 단계부터 파이프라인을 다시 실행합니다:
    - `from_step=2`: 분류부터 재시작
    - `from_step=3`: 파싱부터 재시작 (Upstage API 재호출)
    - `from_step=4`: 전처리부터 재시작
    - `from_step=5`: 청킹부터 재시작
    """,
)
async def reprocess_document(
    document_id: int,
    db: DbSession,
    api_key: ApiKey,
    from_step: int = 3,  # 기본값: 파싱부터 재시작
) -> IngestResponse:
    """
    기존 문서를 재처리합니다.
    
    Args:
        document_id: 문서 ID
        db: 데이터베이스 세션
        api_key: API 키 인증
        from_step: 재시작할 단계 (2=분류, 3=파싱, 4=전처리, 5=청킹)
    """
    # 문서 존재 여부 확인
    doc = await db.get(Document, document_id)
    if not doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"문서 ID {document_id}를 찾을 수 없습니다.",
        )
    
    try:
        # Celery 태스크 실행
        task = reprocess_document_task.delay(document_id, from_step)
        
        logger.info(
            "문서 재처리 태스크 시작됨",
            task_id=task.id,
            document_id=document_id,
            from_step=from_step,
        )
        
        return IngestResponse(
            task_id=task.id,
            message=f"문서 재처리가 시작되었습니다. (Step {from_step}부터)",
            documents_found=1,
        )
        
    except Exception as e:
        logger.exception("재처리 태스크 시작 실패", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"비동기 작업 큐 연결 실패: {str(e)}",
        )


@router.get(
    "/documents",
    response_model=DocumentListResponse,
    summary="인덱싱된 문서 목록",
    description="인덱싱된 모든 문서의 페이지네이트된 목록을 조회합니다.",
)
async def list_documents(
    db: DbSession,
    api_key: ApiKey,
    skip: int = 0,
    limit: int = 20,
    status_filter: str | None = None,
) -> DocumentListResponse:
    """
    인덱싱된 모든 문서를 조회합니다.

    청크 상세 정보 없이 문서 메타데이터만 반환합니다.

    Args:
        skip: 건너뛸 문서 수 (페이지네이션)
        limit: 반환할 최대 문서 수
        status_filter: 상태 필터 (pending, completed, failed 등)
    """
    try:
        # 전체 문서 수 조회
        count_query = select(func.count(Document.id))
        if status_filter:
            count_query = count_query.where(Document.status == status_filter)
        total_result = await db.execute(count_query)
        total = total_result.scalar() or 0

        # 문서 목록 조회 (chunk_count 포함)
        # 서브쿼리로 각 문서의 청크 수 계산
        chunk_count_subq = (
            select(
                DocumentChunk.document_id,
                func.count(DocumentChunk.id).label("chunk_count"),
            )
            .group_by(DocumentChunk.document_id)
            .subquery()
        )

        query = (
            select(
                Document,
                func.coalesce(chunk_count_subq.c.chunk_count, 0).label("chunk_count"),
            )
            .outerjoin(
                chunk_count_subq,
                Document.id == chunk_count_subq.c.document_id,
            )
            .order_by(Document.created_at.desc())
            .offset(skip)
            .limit(limit)
        )

        if status_filter:
            query = query.where(Document.status == status_filter)

        result = await db.execute(query)
        rows = result.all()

        # DocumentInfo 리스트 생성
        documents: list[DocumentInfo] = []
        for row in rows:
            doc = row[0]  # Document 객체
            chunk_count = row[1]  # chunk_count

            documents.append(
                DocumentInfo(
                    id=doc.id,
                    drive_id=doc.drive_id,
                    name=doc.standardized_name or doc.drive_name,
                    doc_type=doc.doc_type.value if doc.doc_type else "other",
                    status=doc.status.value if doc.status else "pending",
                    chunk_count=chunk_count,
                    created_at=doc.created_at,
                    updated_at=doc.updated_at,
                )
            )

        logger.info(
            "Documents listed",
            total=total,
            returned=len(documents),
            skip=skip,
            limit=limit,
        )

        return DocumentListResponse(
            total=total,
            documents=documents,
            skip=skip,
            limit=limit,
        )

    except Exception as e:
        logger.exception("Failed to list documents", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"문서 목록 조회 중 오류가 발생했습니다: {str(e)}",
        )
