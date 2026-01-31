# 📊 Council-AI 프로젝트 분석 리포트 (0131 17:00)

> **분석 시점:** 2026년 1월 31일 17:00  
> **이전 Baseline:** 0131 13:00 리포트

---

## 📈 1. 진행 상황 업데이트 (13:00 → 17:00)

### 핵심 변경 사항

| 영역 | 13:00 상태 | 17:00 상태 | 변화 |
|------|-----------|-----------|------|
| **Pipeline 오케스트레이션** | ❌ 파편화됨 | ✅ Celery 7단계 연결 | 🆕 구현됨 |
| **Chunk → DB 저장** | ❌ 미구현 | ✅ step_06_enrich.py | 🆕 구현됨 |
| **N:M Event-Chunk 관계** | ❌ 미구현 | ✅ DocumentChunk 모델 반영 | 🆕 구현됨 |
| **API → Celery 연결** | ❌ 미구현 | ⚠️ TODO (코드 있지만 비활성화) | 🟡 진행중 |
| **Search API** | ❌ TODO | ❌ TODO (변화 없음) | ⏸️ |

### 신규 구현 세부 사항

#### ✅ Celery 7단계 오케스트레이션 ([tasks/pipeline.py](file:///c:/Users/imtae/madcamp/2025Winter_4th/backend/app/tasks/pipeline.py))
```python
@shared_task(bind=True, name="app.tasks.pipeline.run_full_pipeline")
def run_full_pipeline(self, file_path, filename, drive_id, folder_path):
    # Step 2: Classification
    # Step 3: Parsing  
    # Step 4: Preprocessing
    # Step 5: Chunking
    # Step 6: Enrichment (DB 저장)
    # Step 7: Embedding
    # ✅ 7개 Step이 하나의 Task에서 순차 실행됨
```

#### ✅ Chunk → DB 저장 ([step_06_enrich.py](file:///c:/Users/imtae/madcamp/2025Winter_4th/backend/app/pipeline/step_06_enrich.py))
```python
async def enrich_chunks(self, document, chunks) -> list[DocumentChunk]:
    # 1. Parent chunks 생성 및 DB 저장
    # 2. Child chunks 생성 및 Parent 참조 연결
    # 3. access_level, section_header 주입
    # ✅ 13:00 핵심 누락 사항 해결됨
```

#### ✅ N:M Event-Chunk 관계 ([models/embedding.py](file:///c:/Users/imtae/madcamp/2025Winter_4th/backend/app/models/embedding.py))
```python
class DocumentChunk(Base):
    # ⭐ NEW: Chunk-level Event mapping
    related_event_id = ForeignKey("events.id")  # 청크별 이벤트 연결
    inferred_event_title = String(500)           # LLM 추론 이벤트명
```

---

## ⚡ 2. Celery 파이프라인 진단

### Task 정의 현황

| Task Name | 파일 위치 | 구현 상태 | 비고 |
|-----------|----------|-----------|------|
| [run_full_pipeline](file:///c:/Users/imtae/madcamp/2025Winter_4th/backend/app/tasks/pipeline.py#29-173) | tasks/pipeline.py:29 | ✅ 완료 | 7단계 순차 처리 |
| [ingest_folder](file:///c:/Users/imtae/madcamp/2025Winter_4th/backend/app/api/v1/rag.py#17-71) | tasks/pipeline.py:175 | ✅ 완료 | 폴더 수집 + 개별 파이프라인 |
| [reprocess_document](file:///c:/Users/imtae/madcamp/2025Winter_4th/backend/app/tasks/pipeline.py#281-332) | tasks/pipeline.py | ✅ 완료 | 문서 재처리 |

### API → Celery 연결 상태

| API Endpoint | 연결 상태 | 문제점 |
|--------------|----------|--------|
| `POST /api/v1/rag/ingest/folder` | ⚠️ TODO | Task 호출 코드 **주석 처리됨** |
| `GET /api/v1/tasks/{task_id}` | ⚠️ TODO | AsyncResult 조회 **미구현** |
| `DELETE /api/v1/tasks/{task_id}` | ⚠️ TODO | Task 취소 **미구현** |

#### 문제 코드 (rag.py:61-69)
```python
# TODO: Queue Celery task
# from app.tasks.pipeline import ingest_folder as ingest_folder_task
# task = ingest_folder_task.delay(...)  # ✖️ 주석 처리됨

task_id = f"ingest-{request.folder_id[:8]}-placeholder"  # ✖️ 하드코딩
```

### Worker 실행 가능성

| 항목 | 상태 | 비고 |
|------|------|------|
| Celery 앱 설정 | ✅ | [tasks/celery_app.py](file:///c:/Users/imtae/madcamp/2025Winter_4th/backend/app/tasks/celery_app.py) 존재 |
| Redis 브로커 설정 | ✅ | docker-compose.yml 정의됨 |
| Task 등록 | ✅ | `@shared_task` 데코레이터 사용 |
| async/sync 변환 | ✅ | [run_async()](file:///c:/Users/imtae/madcamp/2025Winter_4th/backend/app/tasks/features.py#23-31) 헬퍼 함수 |

**결론:** Celery Worker는 실행 가능하나, **API에서 Task를 호출하지 않아 테스트 불가능**

---

## 🛑 3. Critical Mismatch Report

### 기획안 대비 불일치 사항

| 기획안 요구사항 | 현재 코드 상태 | 심각도 |
|---------------|---------------|--------|
| **rag_pipeline.md**: `ingest_folder.delay()` 호출 | ❌ API에서 주석 처리됨 | 🔴 Critical |
| **db_schema.md**: ChatLog 테이블 | ❌ 모델 없음 | 🟡 Medium |
| **API.md**: `/search` 구현 | ❌ 빈 배열 반환 | 🔴 Critical |
| **rag_pipeline.md**: Task 상태 polling | ❌ 하드코딩 응답 | 🔴 Critical |

### ⚠️ 가장 긴급한 불일치

```
📍 기획안 (rag_pipeline.md)
────────────────────────────
result = ingest_folder.delay(
    drive_folder_id="1abc...",
    event_hints={"event_title": "2025 축제", "year": 2025}
)

📍 실제 코드 (rag.py)
────────────────────────────
# TODO: Queue Celery task (←주석!)
task_id = "ingest-...-placeholder"  ← 하드코딩!
```

---

## ✅ 4. 기획-코드 일치 항목

### DB Schema (models/)

| 기획안 요구 | 코드 구현 | 일치 |
|------------|----------|------|
| DocumentChunk.related_event_id | ✅ mapping 존재 | ✅ |
| DocumentChunk.inferred_event_title | ✅ 필드 존재 | ✅ |
| DocumentChunk.parent_content | ✅ 필드 존재 | ✅ |
| Event.chunk_timeline (JSONB) | ✅ 필드 존재 | ✅ |
| Access Level (1-4) | ✅ 정의됨 | ✅ |

### Pipeline Logic (pipeline/)

| Step | 기획안 | 코드 구현 | 일치 |
|------|--------|----------|------|
| Step 5: Parent-Child Chunking | ✅ | ✅ step_05_chunk.py | ✅ |
| Step 6: Access Level 결정 | ✅ | ✅ step_06_enrich.py | ✅ |
| Step 7: Vertex AI Embedding | ✅ | ✅ step_07_embed.py | ✅ |

---

## 📋 5. 완성도 요약

| 영역 | 13:00 | 17:00 | 변화 |
|------|-------|-------|------|
| **Ingestion** | ✅ 100% | ✅ 100% | - |
| **Classification** | 🟡 70% | 🟡 70% | - |
| **Parsing** | ✅ 100% | ✅ 100% | - |
| **Preprocessing** | 🟡 70% | ✅ 90% | +20% |
| **Chunking** | 🟡 70% | ✅ 100% | +30% |
| **Enrichment** | 🟡 60% | ✅ 95% | +35% |
| **Embedding** | 🟡 70% | ✅ 95% | +25% |
| **Search** | 🔴 10% | 🔴 10% | - |
| **LLM Answer** | 🔴 0% | 🔴 0% | - |
| **API → Celery** | ❌ 없음 | 🟡 50% | +50% |

---

## 🚀 6. Next Action Items (최우선 3가지)

### 1️⃣ API → Celery 연결 활성화 (15분)

**파일:** [backend/app/api/v1/rag.py](file:///c:/Users/imtae/madcamp/2025Winter_4th/backend/app/api/v1/rag.py)

```python
# ❌ 현재 (주석 처리됨)
# from app.tasks.pipeline import ingest_folder as ingest_folder_task
# task = ingest_folder_task.delay(...)

# ✅ 수정 필요
from app.tasks.pipeline import ingest_folder as ingest_folder_task

task = ingest_folder_task.delay(
    drive_folder_id=request.folder_id,
    options=request.options.model_dump() if request.options else None,
)
return IngestResponse(task_id=task.id, ...)
```

---

### 2️⃣ Task Status API 구현 (15분)

**파일:** [backend/app/api/v1/tasks.py](file:///c:/Users/imtae/madcamp/2025Winter_4th/backend/app/api/v1/tasks.py)

```python
# ❌ 현재 (하드코딩)
return TaskStatusResponse(status=TaskStatus.PENDING, ...)

# ✅ 수정 필요
from celery.result import AsyncResult

result = AsyncResult(task_id)
return TaskStatusResponse(
    task_id=task_id,
    status=_map_celery_status(result.status),
    progress=result.info.get("progress", 0) if result.info else 0,
    result=result.result if result.successful() else None,
)
```

---

### 3️⃣ Search API 기본 구현 (30분)

**파일:** [backend/app/api/v1/rag.py](file:///c:/Users/imtae/madcamp/2025Winter_4th/backend/app/api/v1/rag.py)

```python
from app.pipeline.step_07_embed import EmbeddingService

embedder = EmbeddingService(db)
query_vec = await embedder.embed_single(request.query)
results = await embedder.search_similar(
    query_embedding=query_vec,
    limit=request.top_k,
    access_level=request.access_level,
)

return SearchResponse(
    query=request.query,
    results=results,
    answer=None,  # LLM 답변은 후속 작업
    sources=[r["document_name"] for r in results],
)
```

---

## 📌 결론

| 항목 | 평가 |
|------|------|
| **13:00 대비 진척도** | 🟢 **상당한 진전** - Celery 오케스트레이션, Chunk DB 저장 완료 |
| **기획 정합성** | 🟡 **부분 일치** - DB/Pipeline은 정합, API 연결은 미완 |
| **배포 가능성** | 🔴 **불가** - API → Task 연결이 비활성화 상태 |
| **예상 남은 작업** | ⏱ **약 1시간** - 위 3가지 액션 아이템 기준 |

> **핵심 과제:** API 엔드포인트에서 Celery Task를 실제로 호출하도록 주석 해제 및 연결 필요
