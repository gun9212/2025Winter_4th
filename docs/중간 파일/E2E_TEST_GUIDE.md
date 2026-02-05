# Council-AI E2E 테스트 가이드

## 📋 사전 요구사항 체크리스트

### 1. 인프라 상태 확인

```bash
# Docker 컨테이너 상태 확인
docker-compose ps
```

| 서비스 | 상태 | 포트 |
|--------|------|------|
| ✅ council-backend | Running | 8000 |
| ✅ council-celery | Running | - |
| ✅ redis | Running | 6379 |
| ✅ postgres | Running | 5432 |

### 2. Google API 인증 정보

```yaml
# credentials/google_key.json 확인
{
  "type": "service_account",
  "project_id": "council-ai-xxxxx",
  "private_key_id": "...",
  "private_key": "-----BEGIN PRIVATE KEY-----\n...",
  "client_email": "council-ai@council-ai-xxxxx.iam.gserviceaccount.com",
  ...
}
```

**체크포인트:**
- [ ] `credentials/google_key.json` 파일 존재
- [ ] 서비스 계정 이메일 확인됨
- [ ] Google Cloud Console에서 API 활성화됨
  - [ ] Google Docs API
  - [ ] Google Drive API
  - [ ] Google Calendar API

### 3. 환경 변수 설정

```bash
# .env 또는 docker-compose.yml 확인
GOOGLE_APPLICATION_CREDENTIALS=/app/credentials/google_key.json
GEMINI_API_KEY=your-gemini-api-key
UPSTAGE_API_KEY=your-upstage-api-key
DATABASE_URL=postgresql://user:pass@postgres:5432/council
REDIS_URL=redis://redis:6379/0
```

**체크포인트:**
- [ ] `GEMINI_API_KEY` 설정됨
- [ ] `DATABASE_URL` 연결 가능
- [ ] `REDIS_URL` 연결 가능

---

## 🧪 테스트 데이터 준비

### 1. 테스트용 Google Docs 생성

#### 안건지 템플릿 (Agenda Template)

```
제목: [테스트] 제N차 국장단회의 안건지

# 보고안건

## 보고안건 1: 문화국 MT 준비 현황
담당: 문화국
{{report_1_result}}

## 보고안건 2: 예산 집행 현황
담당: 사무국
{{report_2_result}}

# 논의안건

## 논의안건 1: 축제 일정 조율
담당: 전체
{{discuss_1_result}}

# 의결안건

## 의결안건 1: 예산안 승인
담당: 전체
{{decision_1_result}}
```

**📝 생성 후 Doc ID 기록:**
- 안건지 Doc ID: `_____________________________`

#### 속기록 문서 (Transcript)

```
제목: [테스트] 제N차 국장단회의 속기록

# 보고안건

## 보고안건 1: 문화국 MT 준비 현황
[문화국장]: MT 장소를 오크밸리로 결정했습니다. 
4월 20일까지 예약을 완료할 예정입니다.
[의장]: 예산은 얼마나 필요하신가요?
[문화국장]: 1인당 5만원, 총 50명 기준 250만원입니다.

## 보고안건 2: 예산 집행 현황
[사무국장]: 현재 전체 예산의 40%를 집행했습니다.
다음 주까지 예산안을 정리해서 제출하겠습니다.

# 논의안건

## 논의안건 1: 축제 일정 조율
[의장]: 축제 일정에 대해 논의하겠습니다.
[문화국장]: 5월 첫째 주가 적당할 것 같습니다.
[사무국장]: 동의합니다. 장소는 대운동장으로 하죠.
[의장]: 그럼 5월 3일로 확정하겠습니다.

# 의결안건

## 의결안건 1: 예산안 승인
[의장]: 문화국 MT 예산 250만원 승인 건입니다.
[전원]: 이의 없습니다.
[의장]: 만장일치로 승인되었습니다.
```

**📝 생성 후 Doc ID 기록:**
- 속기록 Doc ID: `_____________________________`

### 2. 서비스 계정에 문서 공유

**중요**: 생성한 모든 테스트 문서에 서비스 계정 이메일을 **편집자**로 추가

```
서비스 계정 이메일: council-ai@council-ai-xxxxx.iam.gserviceaccount.com
```

- [ ] 안건지 문서에 서비스 계정 공유됨
- [ ] 속기록 문서에 서비스 계정 공유됨
- [ ] 출력 폴더에 서비스 계정 공유됨 (선택)

### 3. 테스트용 캘린더 준비

- [ ] Google Calendar에서 테스트 캘린더 생성
- [ ] 서비스 계정에 캘린더 공유 (편집 권한)
- [ ] 캘린더 ID 기록: `_____________________________`

---

## 🚀 E2E 테스트 실행

### Test Case 1: Smart Minutes

#### Step 1: 생성 요청

```bash
curl -X POST "http://localhost:8000/api/v1/minutes/generate" \
  -H "Content-Type: application/json" \
  -d '{
    "agenda_doc_id": "YOUR_AGENDA_DOC_ID",
    "transcript_doc_id": "YOUR_TRANSCRIPT_DOC_ID",
    "meeting_name": "테스트 국장단회의",
    "meeting_date": "2025-04-20"
  }'
```

**예상 응답:**
```json
{
  "task_id": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
  "status": "PENDING",
  "message": "Smart Minutes generation started..."
}
```

- [ ] 200/202 응답 수신
- [ ] task_id 반환됨

**📝 task_id 기록:** `_____________________________`

#### Step 2: 상태 확인 (Polling)

```bash
curl -X GET "http://localhost:8000/api/v1/minutes/{task_id}/status"
```

**예상 응답 (처리 중):**
```json
{
  "task_id": "...",
  "status": "STARTED",
  "progress": 50,
  "current_step": "Summarizing section 2/4"
}
```

**예상 응답 (완료):**
```json
{
  "task_id": "...",
  "status": "SUCCESS",
  "result_doc_id": "NEW_DOC_ID",
  "result_doc_link": "https://docs.google.com/document/d/..."
}
```

- [ ] PENDING → STARTED 전환 확인
- [ ] SUCCESS 상태 도달
- [ ] result_doc_id 반환됨

#### Step 3: 결과 확인

- [ ] Google Docs에서 새 문서 생성됨
- [ ] Placeholder가 실제 내용으로 치환됨
- [ ] 요약 내용이 적절함

---

### Test Case 2: Calendar Sync

#### Step 1: Todo 추출

먼저 결과지 문서를 생성하거나 Test Case 1에서 생성된 문서 사용

```bash
curl -X POST "http://localhost:8000/api/v1/calendar/extract-todos" \
  -H "Content-Type: application/json" \
  -d '{
    "result_doc_id": "YOUR_RESULT_DOC_ID",
    "include_context": true
  }'
```

**예상 응답:**
```json
{
  "todos": [
    {
      "content": "MT 장소 예약",
      "context": "보고안건 1",
      "assignee": "문화국",
      "suggested_date": "4월 20일까지",
      "parsed_date": "2025-04-20"
    }
  ],
  "total_count": 1
}
```

- [ ] 200 응답 수신
- [ ] todos 배열 반환됨
- [ ] 날짜가 올바르게 파싱됨

#### Step 2: 캘린더 이벤트 생성

```bash
curl -X POST "http://localhost:8000/api/v1/calendar/events/create" \
  -H "Content-Type: application/json" \
  -d '{
    "summary": "MT 장소 예약",
    "dt_start": "2025-04-20T10:00:00",
    "dt_end": "2025-04-20T11:00:00",
    "description": "문화국 담당 - 오크밸리 예약",
    "calendar_id": "YOUR_CALENDAR_ID"
  }'
```

**예상 응답:**
```json
{
  "event_id": "xxxxxxxxxxxx",
  "html_link": "https://calendar.google.com/calendar/event?eid=..."
}
```

- [ ] 201 응답 수신
- [ ] event_id 반환됨
- [ ] Google Calendar에서 이벤트 확인됨

---

### Test Case 3: Handover

#### Step 1: 테스트 데이터 입력 (DB)

```sql
-- PostgreSQL에 테스트 데이터 삽입
INSERT INTO events (title, date, category, department)
VALUES 
  ('봄 축제', '2025-05-03', 'festival', '문화국'),
  ('신입생 환영회', '2025-03-10', 'orientation', '문화국');

INSERT INTO documents (event_id, doc_type, google_doc_id)
VALUES 
  (1, 'result', 'DOC_ID_1'),
  (2, 'result', 'DOC_ID_2');
```

#### Step 2: 생성 요청

```bash
curl -X POST "http://localhost:8000/api/v1/handover/generate" \
  -H "Content-Type: application/json" \
  -d '{
    "target_year": 2025,
    "department": "문화국",
    "doc_title": "테스트 인수인계서",
    "include_insights": true
  }'
```

**예상 응답:**
```json
{
  "task_id": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
  "status": "PENDING",
  "message": "Handover generation queued..."
}
```

- [ ] 202 응답 수신
- [ ] task_id 반환됨

#### Step 3: 상태 확인

```bash
curl -X GET "http://localhost:8000/api/v1/handover/{task_id}/status"
```

- [ ] SUCCESS 상태 도달
- [ ] output_doc_id 반환됨
- [ ] Google Docs에서 인수인계서 확인됨

---

## ❌ 에러 시나리오 테스트

### E1: 잘못된 Doc ID

```bash
curl -X POST "http://localhost:8000/api/v1/minutes/generate" \
  -H "Content-Type: application/json" \
  -d '{
    "agenda_doc_id": "INVALID_DOC_ID",
    "transcript_doc_id": "ALSO_INVALID"
  }'
```

**예상:**
- [ ] Task가 FAILURE 상태로 전환
- [ ] error 메시지에 "Document not found" 포함

### E2: 권한 없는 문서

```bash
# 서비스 계정에 공유되지 않은 문서 ID 사용
```

**예상:**
- [ ] 403 또는 FAILURE 상태
- [ ] error 메시지에 "Permission denied" 포함

### E3: 잘못된 캘린더 ID

```bash
curl -X POST "http://localhost:8000/api/v1/calendar/events/create" \
  -H "Content-Type: application/json" \
  -d '{
    "summary": "Test",
    "dt_start": "2025-04-20T10:00:00",
    "calendar_id": "invalid@group.calendar.google.com"
  }'
```

**예상:**
- [ ] 400/403 응답
- [ ] error 메시지에 "Calendar not found" 포함

---

## 📊 성능 벤치마크

| 테스트 케이스 | 시작 시간 | 완료 시간 | 소요 시간 |
|--------------|----------|----------|----------|
| Smart Minutes (4 섹션) | | | |
| Calendar Extract | | | |
| Calendar Create | | | |
| Handover (2 행사) | | | |

---

## 🔍 로그 모니터링

### 실시간 로그 확인

```bash
# Backend 로그
docker logs -f council-backend

# Celery Worker 로그
docker logs -f council-celery
```

### 주요 로그 패턴

```
# 성공 패턴
[INFO] Task generate_minutes[xxx] started
[INFO] Loaded transcript: 2500 characters
[INFO] Split into 4 sections
[INFO] Generated summary for section 1
[INFO] Task generate_minutes[xxx] succeeded

# 에러 패턴
[ERROR] Task generate_minutes[xxx] failed: GoogleAPIError
[ERROR] Document not found: INVALID_ID
```

---

## ✅ 최종 테스트 완료 체크리스트

### Smart Minutes
- [ ] 정상 케이스 통과
- [ ] 에러 케이스 처리됨
- [ ] 결과 문서 품질 확인됨

### Calendar Sync
- [ ] Todo 추출 정상 동작
- [ ] 날짜 파싱 정확함
- [ ] 캘린더 이벤트 생성됨
- [ ] Human-in-the-Loop 흐름 검증됨

### Handover
- [ ] DB 데이터 조회 정상
- [ ] AI 생성 내용 적절함
- [ ] 최종 문서 생성됨

### 전체 시스템
- [ ] Celery 상태 전이 정상 (PENDING → STARTED → SUCCESS)
- [ ] 에러 시 적절한 메시지 반환
- [ ] Google API Rate Limit 이내 동작

---

## 🎯 테스트 자동화 (선택)

```python
# tests/e2e/test_features.py
import pytest
import httpx

BASE_URL = "http://localhost:8000/api/v1"

@pytest.fixture
def test_docs():
    return {
        "agenda_doc_id": "YOUR_TEST_AGENDA_ID",
        "transcript_doc_id": "YOUR_TEST_TRANSCRIPT_ID",
    }

@pytest.mark.asyncio
async def test_minutes_generation(test_docs):
    async with httpx.AsyncClient() as client:
        # 1. 생성 요청
        response = await client.post(
            f"{BASE_URL}/minutes/generate",
            json=test_docs
        )
        assert response.status_code == 202
        task_id = response.json()["task_id"]
        
        # 2. Polling
        for _ in range(30):  # 최대 60초 대기
            status_resp = await client.get(
                f"{BASE_URL}/minutes/{task_id}/status"
            )
            status = status_resp.json()["status"]
            if status == "SUCCESS":
                break
            await asyncio.sleep(2)
        
        assert status == "SUCCESS"
```

---

*Last Updated: 2025-02-02*
