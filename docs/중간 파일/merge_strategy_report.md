# 병합 전략 보고서: origin/main → RAG-pipeline-test

> **작성일:** 2026-01-31  
> **전략:** 아키텍처 권한 유지 (내 구조) + 로직 통합 (팀원 코드 추출)

## 요약

| 항목 | 결정 |
|------|------|
| **아키텍처** | ✅ `RAG-pipeline-test` 유지 (FastAPI, Celery, 7단계 파이프라인) |
| **DB 스키마** | ✅ `RAG-pipeline-test` 유지 (N:M chunk-event, ChatLog) |
| **핵심 로직** | 🔄 `origin/main`에서 추출 → 파이프라인 단계에 주입 |
| **의존성** | 🔄 [requirements.txt](file:///c:/Users/imtae/madcamp/2025Winter_4th/backend/requirements.txt) 합집합 병합 |
| **Alembic** | ✅ 팀원 마이그레이션 삭제, 우리 것 유지 |

---

## 1. 파일 충돌 분석

### 양쪽 브랜치에서 수정된 파일

| 파일 | 조치 | 사유 |
|------|------|------|
| [.env.example](file:///c:/Users/imtae/madcamp/2025Winter_4th/.env.example) | **수동 병합** | 팀원의 새 환경변수 추가 |
| [.gitignore](file:///c:/Users/imtae/madcamp/2025Winter_4th/.gitignore) | **수동 병합** | 패턴 합집합 |
| [backend/Dockerfile](file:///c:/Users/imtae/madcamp/2025Winter_4th/backend/Dockerfile) | **내 것 유지** | 우리 컨테이너 설정이 최신 |
| [backend/requirements.txt](file:///c:/Users/imtae/madcamp/2025Winter_4th/backend/requirements.txt) | **수동 병합** | 합집합, 버전 충돌 확인 |
| [backend/app/core/config.py](file:///c:/Users/imtae/madcamp/2025Winter_4th/backend/app/core/config.py) | **내 것 유지 + 상수 추가** | 누락된 설정 추가 |

### origin/main에만 있는 파일 (신규)

| 파일 | 조치 | 사유 |
|------|------|------|
| [run_ingestion.sh](file:///c:/Users/imtae/madcamp/2025Winter_4th/run_ingestion.sh) | **참조용** | 수동 테스트용 쉘 스크립트 |
| `test_upstage_direct.py` | **테스트 유지** | 파서 테스트에 유용 |
| [backend/app/services/ingestion.py](file:///c:/Users/imtae/madcamp/2025Winter_4th/backend/app/services/ingestion.py) | **로직 추출 → 삭제** | 핵심 로직을 [step_01_ingest.py](file:///c:/Users/imtae/madcamp/2025Winter_4th/backend/app/pipeline/step_01_ingest.py)로 이동 |
| [backend/app/services/parser/upstage.py](file:///c:/Users/imtae/madcamp/2025Winter_4th/backend/app/services/parser/upstage.py) | **로직 추출 → 삭제** | 로직을 [step_03_parse.py](file:///c:/Users/imtae/madcamp/2025Winter_4th/backend/app/pipeline/step_03_parse.py)로 이동 |

### RAG-pipeline-test에만 있는 파일 (모두 유지)

| 파일 | 상태 |
|------|------|
| `backend/alembic/*` | ✅ 유지 (우리 마이그레이션이 정답) |
| `backend/app/pipeline/*` | ✅ 유지 (우리 아키텍처) |
| [backend/app/models/chat.py](file:///c:/Users/imtae/madcamp/2025Winter_4th/backend/app/models/chat.py) | ✅ 유지 (새 ChatLog 모델) |
| `backend/app/schemas/*.py` | ✅ 유지 (업데이트된 스키마) |
| `backend/app/api/v1/{chat,handover,tasks}.py` | ✅ 유지 (새 엔드포인트) |
| [backend/app/tasks/features.py](file:///c:/Users/imtae/madcamp/2025Winter_4th/backend/app/tasks/features.py) | ✅ 유지 (새 Celery 태스크) |

---

## 2. 로직 리팩토링 계획 (핵심)

### 2.1 인제스트 로직: [services/ingestion.py](file:///c:/Users/imtae/madcamp/2025Winter_4th/backend/app/services/ingestion.py) → [pipeline/step_01_ingest.py](file:///c:/Users/imtae/madcamp/2025Winter_4th/backend/app/pipeline/step_01_ingest.py)

#### 추출할 핵심 로직:

```python
# 출처: services/ingestion.py (98-192줄)
# 정확한 파라미터가 포함된 rclone 명령어

cmd = [
    "rclone", "copy",
    f"{RCLONE_REMOTE_NAME}:/",
    str(self.data_path),
    f"--drive-root-folder-id={folder_id}",          # ⭐ 핵심: folder ID 방식
    f"--drive-export-formats={RCLONE_EXPORT_FORMATS}", # docx,xlsx,pptx,pdf
    "--transfers=10",
    "--checkers=8",
    "--contimeout=60s",
    "--timeout=300s",
    "--retries=3",
    "--low-level-retries=10",
    "--stats=30s",
    "-v",
]
# + include 패턴: *.docx, *.xlsx, *.pptx, *.pdf, *.hwp, *.hwpx, *.txt, *.csv, *.jpg, *.jpeg, *.png
# + exclude 패턴: *.gform, * (나머지 전부)
```

#### 대상 위치:

```python
# 목표: pipeline/step_01_ingest.py - IngestionService.sync_from_drive()

# 현재 구현은 --drive-service-account-file 사용
# 병합: 팀원의 include/exclude 패턴 및 timeout 설정 추가
```

#### 로직 매핑 테이블:

| 출처 (ingestion.py) | 대상 (step_01_ingest.py) | 조치 |
|---------------------|-------------------------|------|
| [run_rclone_command()](file:///c:/Users/imtae/madcamp/2025Winter_4th/backend/app/services/ingestion.py#98-192) (L98-192) | [sync_from_drive()](file:///c:/Users/imtae/madcamp/2025Winter_4th/backend/app/pipeline/step_01_ingest.py#81-171) (L81-171) | rclone 옵션 병합 |
| `RCLONE_INCLUDE_PATTERNS` (L55-59) | 클래스 상수로 추가 | 복사 |
| `RCLONE_EXCLUDE_PATTERNS` (L60) | 클래스 상수로 추가 | 복사 |
| `EXTENSION_TO_DOCTYPE` (L28-43) | 추가 또는 참조 | models로 이동 고려 |
| [scan_local_files()](file:///c:/Users/imtae/madcamp/2025Winter_4th/backend/app/services/ingestion.py#237-323) (L237-322) | [list_synced_files()](file:///c:/Users/imtae/madcamp/2025Winter_4th/backend/app/pipeline/step_01_ingest.py#172-207) (L172-206) | 재귀 스캔 로직 병합 |
| [register_files_to_db()](file:///c:/Users/imtae/madcamp/2025Winter_4th/backend/app/services/ingestion.py#392-475) (L392-474) | **신규: 메서드 추가** | 복사 후 async 적용 |
| [sync_folder_to_db()](file:///c:/Users/imtae/madcamp/2025Winter_4th/backend/app/services/ingestion.py#324-391) (L324-390) | **신규: 메서드 추가** | 복사 후 적용 |

---

### 2.2 파서 로직: [services/parser/upstage.py](file:///c:/Users/imtae/madcamp/2025Winter_4th/backend/app/services/parser/upstage.py) → [pipeline/step_03_parse.py](file:///c:/Users/imtae/madcamp/2025Winter_4th/backend/app/pipeline/step_03_parse.py)

#### 추출할 핵심 로직:

```python
# 출처: services/parser/upstage.py (96-206줄)
# 적절한 응답 처리가 포함된 Upstage API 호출

headers = {"Authorization": f"Bearer {self.api_key}"}
async with httpx.AsyncClient(timeout=180.0) as client:
    response = await client.post(
        self.API_URL,
        headers=headers,
        files={"document": f},
        data={"output_format": "markdown"},  # ⭐ markdown 형식
    )

# ⭐ 핵심: Content 추출 로직 (dict/list/string 처리)
def _extract_text_content(self, content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, dict):
        return content.get("text") or content.get("markdown") or ...
    if isinstance(content, list):
        return "\n".join([self._extract_text_content(item) for item in content])
```

#### 대상 위치:

```python
# 목표: pipeline/step_03_parse.py - ParsingService

# 현재 구현은 이미 좋은 구조
# 병합: `_extract_text_content()` 방어적 파싱 추가
# 병합: `parse_and_save()` 파일 I/O 패턴
```

#### 로직 매핑 테이블:

| 출처 (upstage.py) | 대상 (step_03_parse.py) | 조치 |
|-------------------|------------------------|------|
| [_extract_text_content()](file:///c:/Users/imtae/madcamp/2025Winter_4th/backend/app/services/parser/upstage.py#49-95) (L49-94) | **신규: 헬퍼 추가** | 복사 (방어적 파싱) |
| [parse_and_save()](file:///c:/Users/imtae/madcamp/2025Winter_4th/backend/app/services/parser/upstage.py#96-218) (L96-206) | [parse_document()](file:///c:/Users/imtae/madcamp/2025Winter_4th/backend/app/pipeline/step_03_parse.py#77-160)와 통합 | 파일 I/O 참조 |
| Rate limit 스로틀링 (L712-713) | Celery 태스크에 추가 | `await asyncio.sleep(2)` |

---

### 2.3 하이브리드 인제스트 플로우

팀원의 [hybrid_ingestion()](file:///c:/Users/imtae/madcamp/2025Winter_4th/backend/app/services/ingestion.py#723-820) 메서드 (L723-831)가 전체 워크플로우를 보여줍니다:

```python
# 1. rclone 동기화 → 로컬 파일
# 2. Google Drive API → Google Forms URL
# 3. 파일 스캔 및 DB 등록
# 4. Upstage로 파싱
```

**이것은 [tasks/pipeline.py](file:///c:/Users/imtae/madcamp/2025Winter_4th/backend/app/tasks/pipeline.py)의 Celery 태스크 [ingest_folder()](file:///c:/Users/imtae/madcamp/2025Winter_4th/backend/app/api/v1/rag.py#17-71)에 매핑됩니다.**

---

## 3. 의존성 분석

### origin/main에서 추가할 새 의존성:

| 패키지 | 용도 | 충돌 확인 |
|--------|------|-----------|
| `aiofiles` | 파서에서 비동기 파일 I/O | ✅ 충돌 없음 |
| (대부분 이미 있음) | - | - |

### 현재 requirements.txt 비교:

```diff
# 양쪽 브랜치에 있음 (버전 다를 수 있음 - 우리 것 사용):
fastapi, uvicorn, sqlalchemy, asyncpg, celery, redis, 
google-cloud-*, google-generativeai, httpx, structlog

# 누락 시 추가 (팀원 것):
+ aiofiles>=23.2.1
```

---

## 4. Config.py 업데이트

### 추가할 누락된 설정:

```python
# 팀원 config / 환경변수에서:
GOOGLE_DRIVE_FOLDER_ID: str = Field(default="")  # 인제스트용 기본 폴더
SYNC_LOCAL_PATH: str = Field(default="/app/data/raw")
SYNC_LOG_FILE: str = Field(default="/app/logs/sync.log")

# 우리 것에 이미 있거나 다르게 처리됨:
# UPSTAGE_API_KEY ✅ 이미 존재
# DATA_PATH, PROCESSED_PATH ✅ 선택적으로 추가 가능
```

---

## 5. 데이터베이스 및 마이그레이션 검토

### 스키마 비교:

| 항목 | origin/main | RAG-pipeline-test | 결정 |
|------|-------------|-------------------|------|
| `document_chunks.related_event_id` | ❌ 없음 | ✅ 추가됨 | **우리 것 유지** |
| `document_chunks.inferred_event_title` | ❌ 없음 | ✅ 추가됨 | **우리 것 유지** |
| `chat_logs` 테이블 | ❌ 없음 | ✅ 추가됨 | **우리 것 유지** |
| `document.event_id` nullable | ❓ 미확인 | ✅ 명시적 null | **우리 것 유지** |

### 마이그레이션 결정:

> [!IMPORTANT]
> **팀원의 `alembic/versions/*` 파일 삭제.**  
> 우리 마이그레이션 [001_chunk_event_mapping.py](file:///c:/Users/imtae/madcamp/2025Winter_4th/backend/alembic/versions/001_chunk_event_mapping.py)가 첫 번째 마이그레이션으로 권위 있음.

---

## 6. 실행 명령어 초안

### 1단계: 준비

```bash
# 1. RAG-pipeline-test 브랜치 확인
git checkout RAG-pipeline-test

# 2. origin에서 최신 가져오기
git fetch origin

# 3. 백업 브랜치 생성
git branch backup-before-merge

# 4. 팀원 파일을 참조용으로 체크아웃 (일부 이미 완료)
git checkout origin/main -- backend/app/services/ingestion.py
git checkout origin/main -- backend/app/services/parser/upstage.py
git checkout origin/main -- run_ingestion.sh
# 이제 작업 디렉토리에 있지만 커밋되지 않음
```

### 2단계: 수동 병합 (requirements.txt)

```bash
# 팀원 requirements 보기
git show origin/main:backend/requirements.txt > /tmp/theirs_req.txt

# 비교 후 수동 병합
# 추가할 것: aiofiles
```

### 3단계: 로직 추출 (수동 코드 작업)

1. [backend/app/services/ingestion.py](file:///c:/Users/imtae/madcamp/2025Winter_4th/backend/app/services/ingestion.py) 열기 (체크아웃된 참조 파일)
2. [backend/app/pipeline/step_01_ingest.py](file:///c:/Users/imtae/madcamp/2025Winter_4th/backend/app/pipeline/step_01_ingest.py) 열기
3. 위 매핑 테이블에 따라 로직 복사/적용
4. 추출 후 참조 파일 삭제

### 4단계: Config 병합

```bash
# config 비교
git diff HEAD origin/main -- backend/app/core/config.py

# 누락된 설정을 우리 config.py에 수동 추가
```

### 5단계: 정리 및 커밋

```bash
# 참조 파일 제거
rm backend/app/services/ingestion.py
rm run_ingestion.sh

# 스테이징 및 커밋
git add -A
git commit -m "feat: origin/main 인제스트 로직을 파이프라인 구조로 병합"

# 푸시
git push origin RAG-pipeline-test
```

---

## 7. 요약 체크리스트

- [ ] [requirements.txt](file:///c:/Users/imtae/madcamp/2025Winter_4th/backend/requirements.txt) 병합 (누락 시 `aiofiles` 추가)
- [ ] rclone include/exclude 패턴을 [step_01_ingest.py](file:///c:/Users/imtae/madcamp/2025Winter_4th/backend/app/pipeline/step_01_ingest.py)에 추가
- [ ] [IngestionService](file:///c:/Users/imtae/madcamp/2025Winter_4th/backend/app/pipeline/step_01_ingest.py#38-264)에 [register_files_to_db()](file:///c:/Users/imtae/madcamp/2025Winter_4th/backend/app/services/ingestion.py#392-475) 메서드 추가
- [ ] [ParsingService](file:///c:/Users/imtae/madcamp/2025Winter_4th/backend/app/pipeline/step_03_parse.py#51-455)에 [_extract_text_content()](file:///c:/Users/imtae/madcamp/2025Winter_4th/backend/app/services/parser/upstage.py#49-95) 헬퍼 추가
- [ ] 누락된 config 설정 추가 (GOOGLE_DRIVE_FOLDER_ID, 경로들)
- [ ] 팀원 `alembic/versions/*` 삭제 (우리 것 유지)
- [ ] 추출 후 참조 파일 삭제
- [ ] 인제스트 플로우 종단간 테스트

---

## 8. 위험 평가

| 위험 | 완화 방안 |
|------|-----------|
| rclone 옵션 호환 불가 | 작은 폴더로 먼저 테스트 |
| Upstage API 응답 형식 변경 | 팀원의 방어적 파싱이 도움 |
| DB 마이그레이션 충돌 | 우리 것이 권위 있음, 새로 시작 |
| Celery 태스크 시그니처 변경 | 우리 브랜치에서 이미 업데이트됨 |

---

**⏳ 실제 병합 진행 전 승인을 기다립니다.**
