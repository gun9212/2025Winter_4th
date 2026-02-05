# Council-AI 추가 기능 구현 보고서

## 📋 개요

이 문서는 Council-AI 프로젝트의 3가지 핵심 기능 구현 상태와 테스트 가이드를 제공합니다.

- **Smart Minutes**: 안건지 + 속기록 → 결과지 자동 생성
- **Calendar Sync**: 결과지에서 Todo 추출 → 캘린더 등록 (Human-in-the-Loop)
- **Handover**: 연간 데이터 → 인수인계서 자동 생성

---

## 🏗️ 아키텍처 개요

```
┌─────────────────────────────────────────────────────────────────┐
│                        Frontend (Apps Script)                     │
└─────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────┐
│                      FastAPI Backend (API)                        │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐               │
│  │   /minutes  │  │  /calendar  │  │  /handover  │               │
│  │  (Async)    │  │  (Sync)     │  │  (Async)    │               │
│  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘               │
└─────────┼────────────────┼────────────────┼─────────────────────┘
          │                │                │
          ▼                ▼                ▼
┌─────────────────┐  ┌───────────┐  ┌─────────────────┐
│   Celery Task   │  │  Direct   │  │   Celery Task   │
│  (Redis Queue)  │  │  Response │  │  (Redis Queue)  │
└────────┬────────┘  └─────┬─────┘  └────────┬────────┘
         │                 │                 │
         ▼                 ▼                 ▼
┌─────────────────────────────────────────────────────────────────┐
│                     External Services                             │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐               │
│  │ Google Docs │  │  Calendar   │  │   Gemini    │               │
│  │    API      │  │    API      │  │    API      │               │
│  └─────────────┘  └─────────────┘  └─────────────┘               │
└─────────────────────────────────────────────────────────────────┘
```

---

## 📁 파일 구조

```
backend/app/
├── api/v1/
│   ├── minutes_control.py    # Smart Minutes API
│   ├── calendar_control.py   # Calendar Sync API
│   ├── handover_control.py   # Handover API
│   └── tasks_control.py      # 공통 Task 상태 조회
├── tasks/
│   └── features.py           # Celery Tasks 구현
├── services/
│   ├── google/
│   │   ├── docs.py           # Google Docs API
│   │   └── calendar.py       # Google Calendar API
│   ├── ai/
│   │   └── gemini.py         # Gemini AI 서비스
│   └── text_utils.py         # 텍스트 처리 유틸리티
└── schemas/
    └── features_dto.py       # 요청/응답 스키마
```

---

## 🔧 Feature A: Smart Minutes (결과지 자동 생성)

### API Endpoint

```
POST /api/v1/minutes/generate
```

### 요청 스키마

```json
{
  "agenda_doc_id": "1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgvE2upms",
  "transcript_doc_id": "1CyiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgvE2upms",
  "meeting_name": "제5차 집행위원회 국장단 회의",
  "meeting_date": "2025-04-20",
  "output_folder_id": "1DziMVs0XRA5nFMdKvBdBZjgmUUqptlbs"
}
```

### 응답 스키마

```json
{
  "task_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "status": "PENDING",
  "message": "Smart Minutes generation started for '제5차 집행위원회 국장단 회의'"
}
```

### 상태 조회

```
GET /api/v1/minutes/{task_id}/status
```

### cURL 테스트 예시

```bash
# 1. Smart Minutes 생성 요청
curl -X POST "http://localhost:8000/api/v1/minutes/generate" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: your-api-key" \
  -d '{
    "agenda_doc_id": "YOUR_AGENDA_DOC_ID",
    "transcript_doc_id": "YOUR_TRANSCRIPT_DOC_ID",
    "meeting_name": "제5차 국장단회의",
    "meeting_date": "2025-04-20"
  }'

# 2. 상태 확인
curl -X GET "http://localhost:8000/api/v1/minutes/{task_id}/status" \
  -H "X-API-Key: your-api-key"
```

### 처리 흐름

1. **Load**: `transcript_doc_id`로 Google Docs에서 속기록 텍스트 추출
2. **Split**: `text_utils.split_by_headers()`로 안건 단위 분할 (`#`, `##` 헤더 기준)
3. **Summarize**: 각 섹션별 Gemini 요약 (결정사항/논의진전)
4. **Copy**: `agenda_doc_id`를 복제하여 새 문서 생성
5. **Replace**: `{{report_1_result}}`, `{{discuss_1_result}}` 등 Placeholder 치환

### Placeholder 네이밍 규칙

| 안건 유형 | Placeholder 형식 |
|----------|-----------------|
| 보고안건 | `{{report_N_result}}` |
| 논의안건 | `{{discuss_N_result}}` |
| 의결안건 | `{{decision_N_result}}` |
| 기타안건 | `{{other_N_result}}` |

---

## 🔧 Feature B: Calendar Sync (Human-in-the-Loop)

### 1단계: Todo 추출

```
POST /api/v1/calendar/extract-todos
```

### 요청

```json
{
  "result_doc_id": "1EziMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgvE2upms",
  "include_context": true
}
```

### 응답

```json
{
  "todos": [
    {
      "content": "MT 장소 예약",
      "context": "문화국 보고",
      "assignee": "문화국",
      "suggested_date": "4월 20일까지",
      "parsed_date": "2025-04-20"
    },
    {
      "content": "예산안 제출",
      "context": "논의안건 1",
      "assignee": "사무국",
      "suggested_date": "다음 주",
      "parsed_date": null
    }
  ],
  "document_title": "[결과지] 제5차 국장단회의",
  "extracted_at": "2025-04-15T10:30:00",
  "total_count": 2
}
```

### 2단계: 캘린더 이벤트 생성

```
POST /api/v1/calendar/events/create
```

### 요청

```json
{
  "summary": "MT 장소 예약",
  "dt_start": "2025-04-20T10:00:00",
  "dt_end": "2025-04-20T11:00:00",
  "description": "문화국 담당 - 오크밸리 예약 확인",
  "assignee_email": "culture@example.com",
  "calendar_id": "team-calendar@group.calendar.google.com",
  "reminder_minutes": 60
}
```

### cURL 테스트 예시

```bash
# 1. Todo 추출
curl -X POST "http://localhost:8000/api/v1/calendar/extract-todos" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: your-api-key" \
  -d '{
    "result_doc_id": "YOUR_RESULT_DOC_ID",
    "include_context": true
  }'

# 2. 캘린더 이벤트 생성
curl -X POST "http://localhost:8000/api/v1/calendar/events/create" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: your-api-key" \
  -d '{
    "summary": "MT 장소 예약",
    "dt_start": "2025-04-20T10:00:00",
    "calendar_id": "primary"
  }'
```

---

## 🔧 Feature C: Handover (인수인계서 생성)

### API Endpoint

```
POST /api/v1/handover/generate
```

### 요청

```json
{
  "target_year": 2025,
  "department": "문화국",
  "doc_title": "제38대 문화국 인수인계서 (2025)",
  "target_folder_id": "1FziMVs0XRA5nFMdKvBdBZjgmUUqptlbs",
  "include_event_summaries": true,
  "include_insights": true,
  "include_statistics": true
}
```

### 응답

```json
{
  "task_id": "b2c3d4e5-f6g7-8901-bcde-fg2345678901",
  "status": "PENDING",
  "message": "Handover generation for 2025 queued successfully",
  "estimated_time_minutes": 5
}
```

### cURL 테스트 예시

```bash
# 1. 인수인계서 생성 요청
curl -X POST "http://localhost:8000/api/v1/handover/generate" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: your-api-key" \
  -d '{
    "target_year": 2025,
    "include_insights": true
  }'

# 2. 상태 확인
curl -X GET "http://localhost:8000/api/v1/handover/{task_id}/status" \
  -H "X-API-Key: your-api-key"
```

---

## ⚠️ 주의사항

### 1. API 인증

모든 요청에 `X-API-Key` 헤더 필요:
```bash
-H "X-API-Key: your-api-key"
```

### 2. Google API 권한

서비스 계정에 다음 권한이 필요합니다:
- Google Docs API (읽기/쓰기)
- Google Drive API (파일 복사)
- Google Calendar API (이벤트 생성)

**중요**: 문서에 서비스 계정 이메일을 "편집자"로 공유해야 합니다.

### 3. Celery 실행

비동기 작업을 위해 Celery worker가 실행 중이어야 합니다:
```bash
celery -A app.tasks.celery_app worker --loglevel=info
```

### 4. Rate Limiting

- Google Docs API: 분당 300 요청
- Gemini API: 분당 60 요청
- 대량 처리 시 적절한 딜레이 필요

### 5. 문서 Placeholder 형식

Smart Minutes가 정상 작동하려면 안건지 템플릿에 다음 형식의 Placeholder가 있어야 합니다:
```
{{report_1_result}}
{{discuss_1_result}}
{{discuss_2_result}}
...
```

---

## 🔍 디버깅 가이드

### Task 상태 조회

```bash
# 공통 Task 상태 조회 엔드포인트
curl -X GET "http://localhost:8000/api/v1/tasks/{task_id}" \
  -H "X-API-Key: your-api-key"
```

### 로그 확인

```bash
# Backend 로그
docker logs council-backend -f

# Celery Worker 로그
docker logs council-celery -f
```

### 에러 응답 예시

```json
{
  "task_id": "xxx",
  "status": "FAILURE",
  "error": "Google Docs API error: Document not found"
}
```

---

## 📊 성능 기대치

| 기능 | 예상 처리 시간 |
|------|---------------|
| Smart Minutes (10개 안건) | 30초 ~ 1분 |
| Calendar Todo 추출 | 5초 ~ 10초 (Sync) |
| Calendar 이벤트 생성 | 1초 ~ 2초 (Sync) |
| Handover (30개 행사) | 2분 ~ 5분 |

---

## ✅ 테스트 체크리스트

### Smart Minutes
- [ ] 속기록 Google Doc ID로 텍스트 로드 성공
- [ ] 헤더 기반 섹션 분할 정상 동작
- [ ] Gemini 요약 생성 성공
- [ ] 템플릿 복사 및 Placeholder 치환 성공
- [ ] 최종 결과지 Google Docs 링크 반환

### Calendar Sync
- [ ] Todo 추출 JSON 응답 정상
- [ ] 날짜 파싱 성공 (parsed_date 필드)
- [ ] 캘린더 이벤트 생성 성공
- [ ] 담당자 이메일로 참석자 추가

### Handover
- [ ] DB에서 연도별 Event 조회 성공
- [ ] 관련 Document 우선순위 선택 동작
- [ ] Gemini 인수인계서 내용 생성 성공
- [ ] Google Docs 문서 생성 및 내용 입력

---

*Last Updated: 2025-02-02*
