# Council-AI API Specification

> **Version:** 1.0.0  
> **Base URL:** `/api/v1`  
> **Last Updated:** 2025-01-31

## Overview

Council-AI는 학생회 문서 관리를 위한 RAG 기반 API를 제공합니다.

### Authentication

모든 API 요청에 `X-API-Key` 헤더가 필요합니다.

```http
X-API-Key: your-api-key-here
```

---

## Endpoints Summary

| Method | Endpoint                     | Description     | Async |
| ------ | ---------------------------- | --------------- | ----- |
| POST   | `/chat`                      | RAG 채팅        | ❌    |
| GET    | `/chat/history/{session_id}` | 대화 기록 조회  | ❌    |
| POST   | `/rag/ingest/folder`         | 폴더 인제스트   | ✅    |
| POST   | `/rag/search`                | 문서 검색       | ❌    |
| GET    | `/rag/documents`             | 문서 목록       | ❌    |
| POST   | `/minutes/generate`          | 결과지 생성     | ✅    |
| GET    | `/minutes/{task_id}/status`  | 생성 상태 조회  | ❌    |
| POST   | `/calendar/sync`             | 캘린더 동기화   | ✅    |
| POST   | `/calendar/events`           | 이벤트 생성     | ❌    |
| GET    | `/calendar/events`           | 이벤트 목록     | ❌    |
| POST   | `/handover/generate`         | 인수인계서 생성 | ✅    |
| GET    | `/tasks/{task_id}`           | Task 상태 조회  | ❌    |
| DELETE | `/tasks/{task_id}`           | Task 취소       | ❌    |

---

## Chat API

### POST /chat

RAG 기반 멀티턴 대화

**Request:**

```json
{
  "session_id": "uuid-session-id",
  "query": "2024년 축제 예산은 얼마였나요?",
  "user_level": 2,
  "options": {
    "max_results": 5,
    "include_sources": true,
    "year_filter": 2024,
    "department_filter": "문화국"
  }
}
```

**Response:**

```json
{
  "session_id": "uuid-session-id",
  "query": "2024년 축제 예산은 얼마였나요?",
  "rewritten_query": "2024년 대동제 축제 전체 예산 금액",
  "answer": "2024년 대동제 축제의 총 예산은 1,500만원이었습니다...",
  "sources": [
    {
      "doc_id": 123,
      "doc_name": "[결과지] 제5차 문화국 회의",
      "chunk_id": 456,
      "relevance_score": 0.92,
      "excerpt": "축제 예산 확정: 15,000,000원..."
    }
  ],
  "metadata": {
    "total_chunks_searched": 1523,
    "latency_ms": 234,
    "model_used": "gemini-2.0-flash"
  }
}
```

---

## RAG Ingestion API

### POST /rag/ingest/folder

Google Drive 폴더 문서 인제스트

> [!IMPORTANT]  
> `event_id`는 요청 파라미터에 포함되지 않습니다.  
> Event 매핑은 Chunk 레벨에서 LLM이 자동으로 결정합니다.

**Request:**

```json
{
  "folder_id": "1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgvE2upms",
  "options": {
    "is_privacy_sensitive": false,
    "recursive": true,
    "file_types": ["google_doc", "pdf"],
    "exclude_patterns": ["*.tmp", "~*"]
  },
  "user_level": 2
}
```

**Response (202 Accepted):**

```json
{
  "task_id": "ingest-1BxiMVs0-abc123",
  "message": "Document ingestion started. Event mapping will be determined at chunk level.",
  "documents_found": 15
}
```

**Celery Task Payload:**

```json
{
  "task_name": "app.tasks.pipeline.ingest_folder",
  "args": {
    "drive_folder_id": "1BxiMVs0XRA...",
    "options": {
      "is_privacy_sensitive": false,
      "recursive": true,
      "file_types": ["google_doc", "pdf"],
      "exclude_patterns": ["*.tmp"]
    }
  }
}
```

---

## Smart Minutes API

### POST /minutes/generate

안건지 + 녹취록 → 결과지 자동 생성

**Request:**

```json
{
  "agenda_doc_id": "1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgvE2upms",
  "transcript_text": "회의 녹취 내용...",
  "result_template_doc_id": "template-doc-id-optional",
  "meeting_info": {
    "meeting_name": "제7차 국장단회의",
    "meeting_date": "2025-01-30",
    "attendees": ["회장 홍길동", "부회장 임태빈"],
    "department": "집행위원회"
  },
  "output_config": {
    "output_folder_id": "output-folder-id",
    "naming_format": "[결과지] {meeting_name}"
  }
}
```

**Response (202 Accepted):**

```json
{
  "task_id": "minutes-1BxiMVs0-abc123",
  "status": "PENDING",
  "message": "Smart Minutes generation started for '제7차 국장단회의'"
}
```

**Celery Task Payload:**

```json
{
  "task_name": "app.tasks.features.generate_minutes",
  "args": {
    "agenda_doc_id": "...",
    "transcript_text": "...",
    "result_template_doc_id": "...",
    "meeting_info": {...},
    "output_config": {...}
  }
}
```

---

## Calendar Sync API

### POST /calendar/sync

결과지에서 액션 아이템 추출 → 캘린더 이벤트 생성

> [!NOTE]
> `calendar_id`는 **API 파라미터**로 전달됩니다.  
> 이를 통해 여러 캘린더 지원이 가능합니다.

**Request:**

```json
{
  "result_doc_id": "result-doc-id",
  "calendar_id": "primary@council.kaist.ac.kr",
  "options": {
    "create_reminders": true,
    "default_duration_hours": 1,
    "notify_assignees": false,
    "reminder_minutes": [1440, 60]
  },
  "extraction_hints": {
    "date_patterns": ["~까지", "마감일:", "D-day"],
    "assignee_patterns": ["담당:", "담당자:", "책임:"]
  }
}
```

**Response (202 Accepted):**

```json
{
  "task_id": "calendar-sync-result-d-abc123",
  "status": "PENDING",
  "message": "Calendar sync task queued successfully",
  "calendar_id": "primary@council.kaist.ac.kr"
}
```

---

## Handover API

### POST /handover/generate

연도별 인수인계서 자동 생성

**Request:**

```json
{
  "target_year": 2024,
  "department": "문화국",
  "user_level": 1,
  "output_config": {
    "doc_title": "제38대 문화국 인수인계서",
    "output_folder_id": "output-folder-id"
  },
  "content_options": {
    "include_event_summaries": true,
    "include_recommendations": true,
    "include_statistics": true,
    "include_lessons_learned": true,
    "max_events": 50
  },
  "source_filters": {
    "doc_categories": ["meeting_document", "work_document"],
    "meeting_subtypes": ["result", "minutes"],
    "min_access_level": 2
  }
}
```

**Response (202 Accepted):**

```json
{
  "task_id": "handover-2024-abc123",
  "status": "PENDING",
  "message": "Handover generation for 2024 queued successfully",
  "estimated_time_minutes": 5
}
```

---

## Task Status API

### GET /tasks/{task_id}

Celery Task 상태 조회

**Response:**

```json
{
  "task_id": "minutes-1BxiMVs0-abc123",
  "status": "SUCCESS",
  "progress": 100,
  "result": {
    "output_doc_id": "generated-doc-id",
    "output_doc_link": "https://docs.google.com/document/d/...",
    "items_processed": 5
  },
  "error": null,
  "started_at": "2025-01-31T15:30:00Z",
  "completed_at": "2025-01-31T15:31:23Z",
  "task_name": "app.tasks.features.generate_minutes"
}
```

**Status Values:**

| Status     | Description               |
| ---------- | ------------------------- |
| `PENDING`  | 대기 중                   |
| `STARTED`  | 실행 시작                 |
| `PROGRESS` | 진행 중 (progress % 제공) |
| `SUCCESS`  | 완료                      |
| `FAILURE`  | 실패                      |
| `REVOKED`  | 취소됨                    |

### DELETE /tasks/{task_id}

실행 중인 Task 취소

**Response:** `204 No Content`

---

## Error Responses

모든 에러는 다음 형식을 따릅니다:

```json
{
  "detail": "Error message here",
  "error_code": "VALIDATION_ERROR",
  "timestamp": "2025-01-31T15:30:00Z"
}
```

| HTTP Code | Description                         |
| --------- | ----------------------------------- |
| 400       | Bad Request - 잘못된 요청           |
| 401       | Unauthorized - API Key 누락/잘못됨  |
| 403       | Forbidden - 접근 권한 부족          |
| 404       | Not Found - 리소스 없음             |
| 422       | Validation Error - 입력값 검증 실패 |
| 500       | Internal Server Error               |

---

## Access Levels

| Level | Name   | Accessible Docs    |
| ----- | ------ | ------------------ |
| 1     | 회장단 | 모든 문서          |
| 2     | 국장단 | Level 2, 3, 4 문서 |
| 3     | 국원   | Level 3, 4 문서    |
| 4     | 일반   | Level 4 문서만     |

요청 시 `user_level`이 문서의 `access_level`보다 높으면 접근 불가.
