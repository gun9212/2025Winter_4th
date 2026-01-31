"""Celery 태스크 상태 조회 API 엔드포인트.

이 모듈은 비동기 Celery 태스크의 상태를 조회하고 관리하는 API를 제공합니다:
- 태스크 상태 조회 (Polling)
- 태스크 취소 (Revoke)

Redis에 저장된 실제 Celery 태스크 상태를 AsyncResult로 조회합니다.
"""

from datetime import datetime
from typing import Any

import structlog
from celery.result import AsyncResult
from celery.states import PENDING, STARTED, SUCCESS, FAILURE, REVOKED, RETRY
from fastapi import APIRouter, HTTPException, status

from app.api.deps import ApiKey
from app.schemas.task_dto import (
    TaskStatus,
    TaskStatusResponse,
    TaskResult,
)
from app.tasks.celery_app import celery_app

logger = structlog.get_logger()

router = APIRouter()


# Celery 상태 → API 상태 매핑
# Celery는 커스텀 상태도 지원하므로 PROGRESS 등 추가 가능
CELERY_TO_API_STATUS = {
    PENDING: TaskStatus.PENDING,
    STARTED: TaskStatus.STARTED,
    "PROGRESS": TaskStatus.PROGRESS,  # 커스텀 상태
    SUCCESS: TaskStatus.SUCCESS,
    FAILURE: TaskStatus.FAILURE,
    REVOKED: TaskStatus.REVOKED,
    RETRY: TaskStatus.PENDING,  # 재시도 중은 대기 상태로 표시
}


def _map_celery_status(celery_status: str) -> TaskStatus:
    """Celery 상태 문자열을 API TaskStatus enum으로 변환합니다.
    
    Args:
        celery_status: Celery 상태 문자열 (예: 'PENDING', 'SUCCESS')
        
    Returns:
        TaskStatus: 매핑된 API 상태
    """
    return CELERY_TO_API_STATUS.get(celery_status, TaskStatus.PROGRESS)


def _extract_task_result(result_data: Any) -> TaskResult | None:
    """Celery 태스크 결과를 TaskResult 스키마로 변환합니다.
    
    Args:
        result_data: AsyncResult.result에서 얻은 태스크 결과
        
    Returns:
        TaskResult: 파싱된 결과 또는 None
    """
    if not result_data or not isinstance(result_data, dict):
        return None
    
    return TaskResult(
        output_doc_id=result_data.get("output_doc_id"),
        output_doc_link=result_data.get("output_doc_link"),
        items_processed=result_data.get("items_processed", 0),
        events_created=result_data.get("events_created"),
        documents_processed=result_data.get("documents_processed"),
        chunks_created=result_data.get("chunks_created"),
    )


def _extract_progress(info: Any) -> int:
    """태스크 메타정보에서 진행률을 추출합니다.
    
    Args:
        info: AsyncResult.info (상태가 STARTED/PROGRESS일 때 메타정보)
        
    Returns:
        int: 진행률 (0-100)
    """
    if not info or not isinstance(info, dict):
        return 0
    return min(100, max(0, info.get("progress", 0)))


def _extract_error_message(result: Any) -> str:
    """실패한 태스크에서 에러 메시지를 추출합니다.
    
    Args:
        result: AsyncResult.result (FAILURE 상태일 때 Exception)
        
    Returns:
        str: 에러 메시지
    """
    if isinstance(result, Exception):
        return str(result)
    if isinstance(result, dict) and "error" in result:
        return result["error"]
    return str(result) if result else "알 수 없는 오류"


@router.get(
    "/{task_id}",
    response_model=TaskStatusResponse,
    summary="태스크 상태 조회",
    description="""
    Celery 태스크의 현재 상태를 조회합니다.
    
    **상태 값:**
    - `PENDING`: 태스크가 큐에서 대기 중
    - `STARTED`: 태스크 실행 시작됨
    - `PROGRESS`: 태스크 진행 중 (진행률 포함 가능)
    - `SUCCESS`: 태스크 성공적으로 완료
    - `FAILURE`: 태스크 실패 (에러 메시지 포함)
    - `REVOKED`: 태스크가 취소됨
    
    **결과 필드 (SUCCESS 상태):**
    - `output_doc_id`: 생성된 Google Doc ID
    - `output_doc_link`: 출력 문서 직접 링크
    - `items_processed`: 처리된 항목 수
    - `documents_processed`: 처리된 문서 수 (수집용)
    - `chunks_created`: 생성된 청크 수 (수집용)
    
    **Polling 권장 주기:**
    - 초기 5초 → 이후 10초 간격
    - 최대 10분간 폴링 후 타임아웃 처리 권장
    """,
)
async def get_task_status(
    task_id: str,
    api_key: ApiKey,
) -> TaskStatusResponse:
    """
    Celery 태스크의 상태를 조회합니다.
    
    Redis에서 실제 태스크 상태를 AsyncResult로 조회하여
    현재 상태, 진행률, 결과(완료 시)를 반환합니다.
    
    Args:
        task_id: Celery 태스크 ID (UUID 형식)
        api_key: API 키 인증
        
    Returns:
        TaskStatusResponse: 태스크 상태 정보
    """
    try:
        # Redis에서 태스크 상태 조회
        result = AsyncResult(task_id, app=celery_app)
        
        # Celery 상태를 API 상태로 매핑
        api_status = _map_celery_status(result.status)
        
        # 상태별 응답 데이터 구성
        progress = 0
        task_result = None
        error_message = None
        started_at = None
        completed_at = None
        
        if api_status == TaskStatus.PROGRESS or api_status == TaskStatus.STARTED:
            # 진행 중: 메타정보에서 진행률 추출
            progress = _extract_progress(result.info)
            
        elif api_status == TaskStatus.SUCCESS:
            # 성공: 결과 데이터 추출
            progress = 100
            task_result = _extract_task_result(result.result)
            # 완료 시간은 Celery가 자동 저장 (backend 설정에 따라)
            if result.date_done:
                completed_at = result.date_done
                
        elif api_status == TaskStatus.FAILURE:
            # 실패: 에러 메시지 추출
            error_message = _extract_error_message(result.result)
            
        elif api_status == TaskStatus.REVOKED:
            # 취소됨
            progress = 0
        
        # 태스크 이름 추출 (가능한 경우)
        task_name = result.name if hasattr(result, "name") and result.name else None
        
        logger.debug(
            "태스크 상태 조회 완료",
            task_id=task_id,
            status=api_status.value,
            progress=progress,
        )
        
        return TaskStatusResponse(
            task_id=task_id,
            status=api_status,
            progress=progress,
            result=task_result,
            error=error_message,
            started_at=started_at,
            completed_at=completed_at,
            task_name=task_name,
        )
        
    except Exception as e:
        # Redis 연결 실패 등의 예외
        logger.exception("태스크 상태 조회 실패", task_id=task_id, error=str(e))
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"태스크 상태 조회 실패: {str(e)}. Redis 서버 상태를 확인하세요.",
        )


@router.delete(
    "/{task_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="태스크 취소",
    description="""
    대기 중이거나 실행 중인 Celery 태스크를 취소합니다.
    
    **주의사항:**
    - `terminate=True`: 실행 중인 태스크를 강제 종료
    - 이미 완료된 태스크는 취소할 수 없음
    - 취소된 태스크는 `REVOKED` 상태가 됨
    """,
)
async def cancel_task(
    task_id: str,
    api_key: ApiKey,
) -> None:
    """
    Celery 태스크를 취소(revoke)합니다.
    
    대기 중이거나 실행 중인 태스크만 취소할 수 있습니다.
    실행 중인 태스크는 terminate=True로 강제 종료합니다.
    
    Args:
        task_id: 취소할 Celery 태스크 ID
        api_key: API 키 인증
        
    Raises:
        HTTPException: 태스크 취소 실패 시 503 오류
    """
    try:
        result = AsyncResult(task_id, app=celery_app)
        
        # 이미 완료된 태스크인지 확인
        if result.status in (SUCCESS, FAILURE):
            logger.warning(
                "이미 완료된 태스크 취소 시도",
                task_id=task_id,
                status=result.status,
            )
            # 이미 완료된 경우에도 204 반환 (멱등성)
            return None
        
        # 태스크 취소 (terminate=True로 실행 중인 워커도 중단)
        result.revoke(terminate=True)
        
        logger.info("태스크 취소됨", task_id=task_id)
        return None
        
    except Exception as e:
        logger.exception("태스크 취소 실패", task_id=task_id, error=str(e))
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"태스크 취소 실패: {str(e)}",
        )
