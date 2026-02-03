# Council-AI API Specification

> **Version:** 2.0.0  
> **Base URL:** `/api/v1`  
> **Last Updated:** 2026-02-02

## Overview

Council-AI는 학생회 문서 관리를 위한 RAG 기반 API를 제공합니다.

### Authentication

모든 API 요청에 `X-API-Key` 헤더가 필요합니다.

```http
X-API-Key: your-api-key-here
```

---

## Endpoints Summary

| Method | Endpoint                        | Description              | Async | 상태        |
| ------ | ------------------------------- | ------------------------ | ----- | ----------- |
| POST   | `/chat`                         | RAG 멀티턴 채팅          | ❌    | ✅ 구현됨   |
| GET    | `/chat/history/{session_id}`    | 대화 기록 조회           | ❌    | ✅ 구현됨   |
| DELETE | `/chat/history/{session_id}`    | 대화 기록 삭제           | ❌    | ✅ 구현됨   |
| POST   | `/rag/ingest/folder`            | 폴더 인제스트            | ✅    | ✅ 구현됨   |
| POST   | `/rag/search`                   | 문서 검색 + LLM 답변     | ❌    | ✅ 구현됨   |
| GET    | `/rag/documents`                | 문서 목록                | ❌    | ✅ 구현됨   |
| POST   | `/minutes/generate`             | 결과지 생성 (Smart Minutes) | ✅ | ✅ 구현됨   |
| GET    | `/minutes/{task_id}/status`     | 생성 상태 조회           | ❌    | ✅ 구현됨   |
| POST   | `/calendar/extract-todos`       | 할일 추출 (Human-in-Loop)| ❌    | ✅ 구현됨   |
| POST   | `/calendar/events/create`       | 이벤트 생성 (확인 후)    | ❌    | ✅ 구현됨   |
| POST   | `/calendar/sync`                | 자동 캘린더 동기화       | ✅    | ⚠️ Deprecated |
| GET    | `/calendar/events`              | 이벤트 목록              | ❌    | 🔜 TODO     |
| POST   | `/handover/generate`            | 인수인계서 생성          | ✅    | ✅ 구현됨   |
| GET    | `/handover/{task_id}/status`    | 생성 상태 조회           | ❌    | ✅ 구현됨   |
| GET    | `/tasks/{task_id}`              | Task 상태 조회           | ❌    | ✅ 구현됨   |
| DELETE | `/tasks/{task_id}`              | Task 취소                | ❌    | ✅ 구현됨   |

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
    "year_filter": [2024],
    "department_filter": "문화국",
    "semantic_weight": 0.7
  }
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `session_id` | string (UUID) | ❌ | 대화 세션 ID (미입력시 자동 생성) |
| `query` | string | ✅ | 사용자 질문 (1-2000자) |
| `user_level` | int | ❌ | 접근 권한 레벨 (1-4, default: 4) |
| `options.max_results` | int | ❌ | 검색 결과 수 (1-20, default: 5) |
| `options.include_sources` | bool | ❌ | 출처 포함 여부 (default: true) |
| `options.year_filter` | int[] | ❌ | 연도 필터 |
| `options.department_filter` | string | ❌ | 부서 필터 |
| `options.semantic_weight` | float | ❌ | 시맨틱 가중치 (0-1, default: 0.7) |

**Response:**

```json
{
  "session_id": "uuid-session-id",
  "query": "2024년 축제 예산은 얼마였나요?",
  "rewritten_query": "2024년 대동제 축제 전체 예산 금액",
  "answer": "2024년 대동제 축제의 총 예산은 1,500만원이었습니다...",
  "sources": [
    {
      "document_id": 123,
      "document_title": "[결과지] 제5차 문화국 회의",
      "chunk_id": 456,
      "section_header": "## 논의안건 1. 축제 예산",
      "relevance_score": 0.92,
      "drive_link": "https://docs.google.com/...",
      "event_title": "2024 대동제"
    }
  ],
  "metadata": {
    "total_chunks_searched": 1523,
    "latency_ms": 234,
    "retrieval_latency_ms": 89,
    "generation_latency_ms": 145,
    "model_used": "gemini-2.0-flash"
  }
}
```

### GET /chat/history/{session_id}

대화 세션 기록 조회 (Redis에서 가져옴, TTL 1시간)

**Response:**

```json
{
  "session_id": "uuid-session-id",
  "history": [
    {"role": "user", "content": "축제 예산은?", "timestamp": "2026-02-02T10:00:00Z"},
    {"role": "assistant", "content": "2024년 대동제...", "timestamp": "2026-02-02T10:00:02Z"}
  ],
  "turn_count": 2
}
```

### DELETE /chat/history/{session_id}

대화 세션 기록 삭제

**Response:** `204 No Content`

---

## RAG API

### POST /rag/ingest/folder

Google Drive 폴더 문서 인제스트 (Celery 비동기)

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
    "file_types": ["google_doc", "pdf", "docx"],
    "exclude_patterns": ["*.tmp", "~*"],
    "skip_sync": false
  },
  "user_level": 2
}
```

**Response (202 Accepted):**

```json
{
  "task_id": "550e8400-e29b-41d4-a716-446655440000",
  "message": "Document ingestion started. Event mapping will be determined at chunk level.",
  "documents_found": 15
}
```

### POST /rag/search

문서 검색 + LLM 답변 생성

**Request:**

```json
{
  "query": "2024년 축제 예산",
  "top_k": 5,
  "include_context": true,
  "generate_answer": true
}
```

**Response:**

```json
{
  "query": "2024년 축제 예산",
  "results": [
    {
      "document_id": 123,
      "document_name": "[결과지] 제5차 문화국 회의",
      "chunk_content": "축제 예산 확정: 15,000,000원...",
      "similarity_score": 0.92,
      "metadata": { "year": 2024, "department": "문화국" }
    }
  ],
  "answer": "2024년 축제의 총 예산은 1,500만원으로 확정되었습니다...",
  "sources": [...],
  "partner_info": null
}
```

### GET /rag/documents

인덱싱된 문서 목록 조회

**Query Parameters:**

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `skip` | int | 0 | 페이지네이션 오프셋 |
| `limit` | int | 20 | 페이지 크기 (max: 100) |
| `status` | string | - | 상태 필터 (pending, processing, completed, failed) |

**Response:**

```json
{
  "total": 150,
  "documents": [
    {
      "id": 1,
      "drive_id": "1abc...",
      "name": "[결과지] 제1차 국장단회의",
      "doc_type": "google_doc",
      "status": "completed",
      "chunk_count": 12,
      "created_at": "2026-01-15T10:00:00Z",
      "updated_at": "2026-01-15T10:05:00Z"
    }
  ],
  "skip": 0,
  "limit": 20
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
  "transcript_doc_id": "1xyz789...",
  "meeting_name": "제12차 운영위원회",
  "meeting_date": "2026-02-02",
  "output_folder_id": "1abc123...",
  "user_level": 2
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `agenda_doc_id` | string | ✅ | Google Docs 안건지 ID |
| `transcript_doc_id` | string | ⚠️ | Google Docs 속기록 ID (둘 중 하나 필수) |
| `transcript_text` | string | ⚠️ | 속기록 텍스트 직접 입력 (둘 중 하나 필수) |
| `template_doc_id` | string | ❌ | 결과 템플릿 ID (미입력시 안건지 복사) |
| `meeting_name` | string | ✅ | 회의명 |
| `meeting_date` | date | ✅ | 회의일자 |
| `output_folder_id` | string | ❌ | 결과 문서 저장 폴더 ID |
| `output_doc_id` | string | ❌ | 미리 생성된 결과 문서 ID (quota 우회용) |
| `user_level` | int | ❌ | 접근 권한 (1-4, default: 2) |

**Response (202 Accepted):**

```json
{
  "task_id": "minutes-1BxiMVs0-abc123",
  "status": "PENDING",
  "message": "Smart Minutes generation started for '제12차 운영위원회'"
}
```

**Placeholder Convention:**
- `{{report_N_result}}` - 보고안건 N 결과
- `{{discuss_N_result}}` - 논의안건 N 결과
- `{{decision_N_result}}` - 의결안건 N 결과
- `{{other_N_result}}` - 기타안건 N 결과

### GET /minutes/{task_id}/status

생성 작업 상태 조회

**Response:**

```json
{
  "task_id": "minutes-1BxiMVs0-abc123",
  "status": "SUCCESS",
  "progress": 100,
  "result_doc_id": "1newDocId...",
  "result_doc_link": "https://docs.google.com/document/d/1newDocId/edit",
  "error": null
}
```

---

## Calendar API (Human-in-the-Loop)

### POST /calendar/extract-todos

결과지에서 할일/일정 추출 (사용자 확인 단계)

**Request:**

```json
{
  "result_doc_id": "1xyz789...",
  "include_context": true
}
```

**Response:**

```json
{
  "todos": [
    {
      "content": "축제 가수 계약서 발송",
      "context": "## 논의안건 1. 가수 섭외 건에서 추출",
      "assignee": "문화국장",
      "suggested_date": "다음 주 금요일까지",
      "parsed_date": "2026-02-07"
    },
    {
      "content": "예산안 최종 제출",
      "context": "## 의결안건 2. 예산 확정에서 추출",
      "assignee": null,
      "suggested_date": "빠른 시일 내",
      "parsed_date": null
    }
  ],
  "document_title": "[결과지] 제12차 운영위원회",
  "extracted_at": "2026-02-02T12:00:00Z",
  "total_count": 2
}
```

### POST /calendar/events/create

사용자 확인 후 캘린더 이벤트 생성

**Request:**

```json
{
  "summary": "축제 가수 계약서 발송",
  "dt_start": "2026-02-07T09:00:00",
  "dt_end": "2026-02-07T10:00:00",
  "description": "제12차 운영위원회 결정사항",
  "assignee_email": "culture@kaist.ac.kr",
  "calendar_id": "primary",
  "reminder_minutes": 60,
  "source_doc_id": "1xyz789..."
}
```

**Response (201 Created):**

```json
{
  "event_id": "abc123xyz",
  "calendar_id": "primary",
  "summary": "축제 가수 계약서 발송",
  "start_time": "2026-02-07T09:00:00Z",
  "end_time": "2026-02-07T10:00:00Z",
  "html_link": "https://calendar.google.com/event?eid=abc123",
  "created_at": "2026-02-02T12:05:00Z"
}
```

### POST /calendar/sync (⚠️ Deprecated)

> [!WARNING]
> 이 엔드포인트는 Deprecated 되었습니다.  
> 대신 `/calendar/extract-todos` + `/calendar/events/create` 조합을 사용하세요.

---

## Handover API

### POST /handover/generate

연도별 인수인계서 자동 생성

**Request:**

```json
{
  "target_year": 2025,
  "department": "문화국",
  "target_folder_id": "1abc123...",
  "doc_title": "2025년 문화국 인수인계서",
  "include_event_summaries": true,
  "include_insights": true,
  "include_statistics": true,
  "user_level": 1
}
```

**Response (202 Accepted):**

```json
{
  "task_id": "handover-2025-abc123",
  "status": "PENDING",
  "message": "Handover document generation started for 2025",
  "estimated_time_minutes": 5
}
```

### GET /handover/{task_id}/status

생성 작업 상태 조회

**Response:**

```json
{
  "task_id": "handover-2025-abc123",
  "status": "SUCCESS",
  "progress": 100,
  "output_doc_id": "1newHandover...",
  "output_doc_link": "https://docs.google.com/document/d/1newHandover/edit",
  "events_summarized": 15,
  "total_documents_analyzed": 45
}
```

---

## Task Status API

### GET /tasks/{task_id}

Celery Task 상태 조회

**Response:**

```json
{
  "task_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "PROGRESS",
  "progress": 65,
  "result": null,
  "error": null,
  "started_at": "2026-02-02T12:00:00Z",
  "completed_at": null,
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
  "timestamp": "2026-02-02T15:30:00Z"
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
| 503       | Service Unavailable - Redis 연결 실패 |

---

## Access Levels

| Level | Name   | Accessible Docs    |
| ----- | ------ | ------------------ |
| 1     | 회장단 | 모든 문서          |
| 2     | 국장단 | Level 2, 3, 4 문서 |
| 3     | 국원   | Level 3, 4 문서    |
| 4     | 일반   | Level 4 문서만     |

요청 시 `user_level`이 문서의 `access_level`보다 높으면 접근 불가.

---

## 변경 이력

| 버전 | 날짜 | 변경 내용 |
|------|------|-----------|
| 1.0.0 | 2025-01-31 | 초기 작성 |
| 2.0.0 | 2026-02-02 | Human-in-the-Loop 캘린더 API 추가, output_doc_id 파라미터 추가, 구현 상태 반영 |
