"""RAG (Retrieval-Augmented Generation) API endpoints.

이 모듈은 RAG 시스템의 핵심 API 엔드포인트를 정의합니다:
- 문서 수집 (Ingestion): Celery 태스크로 비동기 처리
- 검색 (Search): 벡터 유사도 기반 검색 (팀원 담당)
- 문서 목록 조회
"""

import structlog
from fastapi import APIRouter, HTTPException, status

from app.api.deps import ApiKey, DbSession
from app.schemas.rag_dto import (
    DocumentListResponse,
    IngestRequest,
    IngestResponse,
    SearchRequest,
    SearchResponse,
)

# Celery 태스크 import
from app.tasks.pipeline import ingest_folder as ingest_folder_task

logger = structlog.get_logger()

router = APIRouter()


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
    
    TODO: 팀원이 구현 예정
    - 쿼리 임베딩
    - pgvector로 벡터 유사도 검색
    - 하이브리드 스코어링 (시맨틱 + 시간 가중치) 적용
    - access_level로 필터링
    - Parent 컨텍스트와 함께 LLM 응답 생성
    """
    # TODO: RAG 검색 구현 (팀원 담당)
    
    return SearchResponse(
        query=request.query,
        results=[],
        answer=None,
        sources=[],
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
) -> DocumentListResponse:
    """
    인덱싱된 모든 문서를 조회합니다.
    
    청크 상세 정보 없이 문서 메타데이터만 반환합니다.
    
    TODO: 데이터베이스에서 문서 목록 조회 구현
    """
    return DocumentListResponse(
        total=0,
        documents=[],
        skip=skip,
        limit=limit,
    )
