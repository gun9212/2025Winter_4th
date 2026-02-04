# RAG Pipeline Issue Analysis

## 🔍 문제 요약

| #   | 증상                                                                | 심각도    | 영향                                                          |
| --- | ------------------------------------------------------------------- | --------- | ------------------------------------------------------------- |
| 1   | `LLM parsing failed: Event loop is closed`                          | 🟡 Medium | preprocessing 단계에서 에러 발생하지만 파이프라인은 계속 진행 |
| 2   | `'InterceptedUnaryUnaryCall' has no attribute '_interceptors_task'` | 🟢 Low    | gRPC 정리 중 발생하는 경고 (기능에 영향 없음)                 |
| 3   | 과거 pending 문서가 계속 처리됨                                     | 🔴 High   | 원하지 않는 파일들이 반복적으로 처리됨                        |

---

## 📋 문제 1: Event Loop is Closed

### 증상

```
[error] LLM parsing failed  error='Event loop is closed'
[error] Preprocessing failed error='Event loop is closed'
```

### 근본 원인

**Celery Worker와 asyncio의 충돌**

1. [pipeline.py](file:///c:/Users/imtae/madcamp/2025Winter_4th/backend/app/tasks/pipeline.py#L26-L33)의 [run_async()](file:///c:/Users/imtae/madcamp/2025Winter_4th/backend/app/tasks/pipeline.py#26-34) 함수가 **매번 새로운 이벤트 루프를 생성하고 닫음**:

   ```python
   def run_async(coro):
       loop = asyncio.new_event_loop()
       asyncio.set_event_loop(loop)
       try:
           return loop.run_until_complete(coro)
       finally:
           loop.close()  # ← 여기서 루프가 닫힘
   ```

2. `google.generativeai` (Gemini SDK)가 **내부적으로 이벤트 루프를 캐싱**하고 재사용하려 함

3. [step_02_classify.py](file:///c:/Users/imtae/madcamp/2025Winter_4th/backend/app/pipeline/step_02_classify.py#L18-L24)에서 **모듈 로드 시점에** Gemini를 구성:

   ```python
   # 모듈 레벨에서 실행됨 - 이벤트 루프 컨텍스트 없이
   genai.configure(api_key=settings.GEMINI_API_KEY)
   ```

4. 결과: 첫 번째 태스크 후 이벤트 루프가 닫히면, 후속 Gemini API 호출이 실패

### 영향

- Classification에서 LLM 호출 실패 시 → **regex fallback** 사용 (기능 유지)
- Preprocessing에서 LLM 실패 시 → **basic cleanup** fallback 사용 (기능 유지)
- **파이프라인은 계속 진행되지만, LLM 기반 구조화가 누락됨**

---

## 📋 문제 2: InterceptedUnaryUnaryCall AttributeError

### 증상

```
AttributeError: 'InterceptedUnaryUnaryCall' object has no attribute '_interceptors_task'
```

### 근본 원인

**gRPC 비동기 리소스 정리 문제**

1. Vertex AI Text Embedding API는 gRPC 기반
2. 이벤트 루프가 닫힐 때 gRPC 객체의 `__del__` 메서드가 호출됨
3. 이미 닫힌 이벤트 루프에서 비동기 정리 작업 시도 → AttributeError

### 영향

- **기능에 영향 없음** - 이미 처리가 완료된 후 정리 단계에서 발생
- 로그 노이즈만 발생

---

## 📋 문제 3: 과거 Pending 문서 처리

### 증상

```
Continuing processing of existing document current_status=pending
drive_id='local:1HFy-EwIEvtWS0eke-TGOPFCFmKY0J1Wo/프로그램1국/...'
```

GAS 학습된 문서에 올리지 않은 파일들이 표시됨:

- `[별첨1] 2024 ComSee 전체 진행 PPT.pptx`
- `기묘한 컴공 이야기_용의자 리스트.pptx`
- 등 수십개 파일

### 근본 원인

**Drive 폴더에 과거 파일이 계속 존재**

1. 팀원이 이전에 `1xPdCq4GBdkZz5VdR3-QdwMW_qgBoVhOx` 폴더로 많은 파일을 업로드함
2. Cloud SQL을 TRUNCATE해도 **Google Drive 폴더의 파일은 그대로 남아있음**
3. [ingest_folder](file:///c:/Users/imtae/madcamp/2025Winter_4th/backend/app/tasks/pipeline.py#271-382) 태스크가 다시 실행되면:
   - rclone이 Drive 폴더에서 모든 파일을 다시 동기화
   - [register_files_to_db()](file:///c:/Users/imtae/madcamp/2025Winter_4th/backend/app/pipeline/step_01_ingest.py#416-497)가 모든 파일을 DB에 등록
   - [run_full_pipeline()](file:///c:/Users/imtae/madcamp/2025Winter_4th/backend/app/tasks/pipeline.py#69-269)이 모든 파일에 대해 트리거됨

### 파이프라인 흐름

```mermaid
flowchart TD
    A[GAS: 폴더 학습] --> B[ingest_folder 태스크]
    B --> C[rclone sync: Drive → 서버]
    C --> D[scan_local_files]
    D --> E[register_files_to_db]
    E --> F{각 파일마다}
    F --> G[run_full_pipeline 태스크]
    G --> H[Cloud SQL에 저장]
```

**핵심 문제**: rclone은 **Drive 폴더의 모든 파일**을 동기화. 특정 파일만 선택하는 로직이 없음.

---

## ✅ 해결 방안

### 🔧 즉시 해결: Cloud SQL + Redis + 서버 파일 모두 정리

```bash
# 1. Cloud SQL 데이터 전체 삭제
docker run -it --rm postgres:16 psql "postgresql://postgres:madcamp1234@34.47.64.114:5432/council-ai-sql" -c "
TRUNCATE TABLE document_chunks, documents, events, \"references\", chat_logs CASCADE;
"

# 2. Redis (Celery 큐) 비우기
docker exec council-ai-redis redis-cli FLUSHDB

# 3. 서버의 synced 파일 삭제 (핵심!)
sudo rm -rf /app/data/raw/*

# 4. Celery worker 재시작
docker-compose restart celery_worker
```

### 🔧 테스트용 폴더 변경

현재 폴더 (`1xPdCq4GBdkZz5VdR3-QdwMW_qgBoVhOx`)에는 팀원이 올린 파일이 많으므로:

1. **새 테스트 폴더 생성**: Google Drive에 새 폴더 만들기
2. **테스트 파일만 업로드**: 안건지 + 속기록 2개만 업로드
3. **새 폴더 ID로 학습**: GAS에서 새 폴더 선택

---

## 📊 preprocessed_content 확인 방법

파이프라인이 완료된 후:

```bash
docker run -it --rm postgres:16 psql "postgresql://postgres:madcamp1234@34.47.64.114:5432/council-ai-sql" -c "
SELECT
    id,
    filename,
    doc_category,
    meeting_subtype,
    status,
    LENGTH(preprocessed_content) AS content_length,
    CASE
        WHEN preprocessed_content LIKE '%#%' THEN 'YES'
        ELSE 'NO'
    END AS has_headers
FROM documents
WHERE status = 'completed'
ORDER BY created_at DESC
LIMIT 5;
"
```

---

## 🚧 장기 개선 사항 (Optional)

### Event Loop 문제 해결

[pipeline.py](file:///c:/Users/imtae/madcamp/2025Winter_4th/backend/app/tasks/pipeline.py)에서:

```python
# 현재 (문제)
def run_async(coro):
    loop = asyncio.new_event_loop()
    ...
    finally:
        loop.close()  # Gemini SDK 내부 상태와 충돌

# 개선안: nest_asyncio 사용 또는 동기 SDK 사용
```

### 선택적 파일 처리

[ingest_folder](file:///c:/Users/imtae/madcamp/2025Winter_4th/backend/app/tasks/pipeline.py#271-382)에 파일 필터링 옵션 추가:

- 특정 파일명 패턴만 처리
- 수정 날짜 기준 필터링
- Google Drive에서 직접 파일 ID 목록 전달
