# 🚀 Council-AI 개발 환경 구축 가이드

> **작성일:** 2026-01-31  
> **대상:** Windows + PowerShell 환경

---

## 📋 목차

1. [사전 요구사항](#1-사전-요구사항)
2. [Step 1: Python 패키지 설치](#step-1-python-패키지-설치)
3. [Step 2: 환경 변수 설정](#step-2-환경-변수-설정)
4. [Step 3: Docker 서비스 시작](#step-3-docker-서비스-시작)
5. [Step 4: FastAPI 서버 시작](#step-4-fastapi-서버-시작)
6. [Step 5: Celery Worker 시작](#step-5-celery-worker-시작)
7. [Step 6: API 테스트](#step-6-api-테스트)
8. [트러블슈팅](#트러블슈팅)

---

## 1. 사전 요구사항

| 도구           | 버전  | 확인 명령          |
| -------------- | ----- | ------------------ |
| Python         | 3.11+ | `python --version` |
| Docker Desktop | 최신  | `docker --version` |
| Git            | 최신  | `git --version`    |

---

## Step 1: Python 패키지 설치

### 1-1. 가상환경 생성 (최초 1회)

```powershell
# 프로젝트 루트에서 실행
cd c:\Users\imtae\madcamp\2025Winter_4th

# 가상환경 생성
python -m venv venv

# 가상환경 활성화 (PowerShell)
.\venv\Scripts\Activate.ps1
```

> ⚠️ **실행 정책 오류 시:**
>
> ```powershell
> Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
> ```

### 1-2. 패키지 설치

```powershell
# 가상환경 활성화 상태에서
cd backend
pip install -r requirements.txt
```

**설치되는 주요 패키지:**
| 패키지 | 버전 | 용도 |
|--------|------|------|
| `fastapi` | 0.109.2 | 웹 프레임워크 |
| `celery[redis]` | 5.3.6 | 비동기 태스크 큐 |
| `redis` | 5.0.1 | Celery 메시지 브로커 클라이언트 |
| `sqlalchemy[asyncio]` | 2.0.25 | ORM (비동기) |
| `pgvector` | 0.2.5 | 벡터 검색 |
| `google-cloud-aiplatform` | 1.38.0 | Vertex AI |
| `structlog` | 24.1.0 | 구조화된 로깅 |

---

## Step 2: 환경 변수 설정

### 2-1. `.env` 파일 생성

```powershell
# backend 폴더에서 실행
cd c:\Users\imtae\madcamp\2025Winter_4th\backend
Copy-Item .env.example .env
```

### 2-2. `.env` 파일 편집

메모장이나 VS Code로 `backend\.env`를 열고 아래 값들을 실제 값으로 변경:

```ini
# 필수 API 키 (반드시 변경!)
GEMINI_API_KEY=실제-gemini-api-키
UPSTAGE_API_KEY=실제-upstage-api-키

# GCP 프로젝트 (Vertex AI 사용 시)
GOOGLE_CLOUD_PROJECT=your-gcp-project-id

# 나머지는 로컬 개발 시 기본값 사용 가능
```

**API 키 발급처:**

- Gemini: https://aistudio.google.com/apikey
- Upstage: https://console.upstage.ai/

---

## Step 3: Docker 서비스 시작

### 3-1. Docker Desktop 실행

Windows 시작 메뉴에서 **Docker Desktop** 실행

### 3-2. PostgreSQL + Redis 시작

```powershell
# 프로젝트 루트에서 실행
cd c:\Users\imtae\madcamp\2025Winter_4th

# DB와 Redis만 시작 (backend, celery는 로컬에서 실행)
docker-compose up -d db redis
```

**각 서비스 역할:**
| 서비스 | 포트 | 역할 |
|--------|------|------|
| `db` | 5432 | PostgreSQL + pgvector (벡터 DB) |
| `redis` | 6379 | Celery 메시지 브로커 & 결과 저장소 |

### 3-3. 서비스 상태 확인

```powershell
docker-compose ps
```

**정상 출력:**

```
NAME               STATUS    PORTS
council-ai-db      running   0.0.0.0:5432->5432/tcp
council-ai-redis   running   0.0.0.0:6379->6379/tcp
```

### 3-4. Redis 연결 테스트

```powershell
docker exec council-ai-redis redis-cli ping
```

**예상 응답:** `PONG`

---

## Step 4: FastAPI 서버 시작

### 4-1. 서버 실행 (터미널 1)

```powershell
# 가상환경 활성화
cd c:\Users\imtae\madcamp\2025Winter_4th
.\venv\Scripts\Activate.ps1

# backend 폴더로 이동
cd backend

# uvicorn으로 서버 시작
python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

**성공 시 출력:**

```
INFO:     Uvicorn running on http://0.0.0.0:8000 (Press CTRL+C to quit)
INFO:     Started reloader process
```

### 4-2. 서버 확인

브라우저에서 http://localhost:8000/docs 접속 → Swagger UI 확인

---

## Step 5: Celery Worker 시작

### 5-1. 새 터미널 열기 (터미널 2)

```powershell
# 가상환경 활성화
cd c:\Users\imtae\madcamp\2025Winter_4th
.\venv\Scripts\Activate.ps1

# backend 폴더로 이동
cd backend
```

### 5-2. Celery Worker 실행

```powershell
# celery 명령어 직접 실행 (가상환경 내)
python -m celery -A app.tasks.celery_app worker --loglevel=info --pool=solo
```

> ⚠️ **Windows에서 `--pool=solo` 필수!**  
> Windows는 기본 prefork 풀을 지원하지 않습니다.

**성공 시 출력:**

```
 -------------- celery@DESKTOP-XXX v5.3.6 (emerald-rush)
--- ***** -----
-- ******* ---- Windows-10-xxx
- *** --- * ---
- ** ---------- [config]
- ** ---------- .> app:         council_ai:0x...
- ** ---------- .> transport:   redis://localhost:6379/0
- *** --- * --- .> results:     redis://localhost:6379/0
-- ******* ---- .> concurrency: 4 (solo)
--- ***** -----
 -------------- [queues]
                .> celery       exchange=celery(direct) key=celery
                .> pipeline     exchange=pipeline(direct) key=pipeline

[tasks]
  . app.tasks.pipeline.ingest_folder
  . app.tasks.pipeline.run_full_pipeline
```

---

## Step 6: API 테스트

### 6-1. PowerShell에서 API 호출

> ⚠️ **PowerShell의 `curl`은 `Invoke-WebRequest`의 별칭입니다!**  
> 리눅스 스타일 `curl` 명령어가 작동하지 않습니다.

```powershell
# POST 요청 (PowerShell 문법)
$body = @{
    folder_id = "test-folder-id"
} | ConvertTo-Json

Invoke-RestMethod -Uri "http://localhost:8000/api/v1/rag/ingest/folder" `
    -Method Post `
    -Headers @{"X-API-Key"="test-key"; "Content-Type"="application/json"} `
    -Body $body
```

### 6-2. 또는 Swagger UI 사용 (권장)

1. 브라우저에서 http://localhost:8000/docs 접속
2. `POST /api/v1/rag/ingest/folder` 엔드포인트 클릭
3. "Try it out" 클릭
4. Request body 입력:
   ```json
   {
     "folder_id": "test-folder-id",
     "options": {
       "is_privacy_sensitive": false,
       "recursive": true
     }
   }
   ```
5. "Execute" 클릭

### 6-3. Task 상태 확인

```powershell
# task_id는 위 응답에서 받은 값
Invoke-RestMethod -Uri "http://localhost:8000/api/v1/tasks/{task_id}" `
    -Method Get `
    -Headers @{"X-API-Key"="test-key"}
```

---

## 트러블슈팅

### ❌ `celery : The term 'celery' is not recognized`

**원인:** 가상환경 미활성화 또는 PATH 문제

**해결:**

```powershell
# 1. 가상환경 활성화 확인
.\venv\Scripts\Activate.ps1

# 2. python -m 으로 실행
python -m celery -A app.tasks.celery_app worker --loglevel=info --pool=solo
```

### ❌ `curl` 명령어 오류

**원인:** PowerShell은 리눅스 스타일 `curl` 미지원

**해결:** `Invoke-RestMethod` 사용 또는 Swagger UI(`/docs`) 사용

### ❌ Redis 연결 실패 (Connection refused)

**원인:** Redis 컨테이너 미실행

**해결:**

```powershell
docker-compose up -d redis
docker-compose ps  # 상태 확인
```

### ❌ PostgreSQL 연결 실패

**원인:** DB 컨테이너 미실행 또는 마이그레이션 미적용

**해결:**

```powershell
# 1. 컨테이너 실행
docker-compose up -d db

# 2. 마이그레이션 실행 (최초 1회)
cd backend
python -m alembic upgrade head
```

---

## 📁 프로젝트 디렉토리 구조 참고

```
2025Winter_4th/
├── backend/
│   ├── app/
│   │   ├── api/v1/           # Controller 계층 (*_control.py)
│   │   ├── schemas/          # DTO 계층 (*_dto.py)
│   │   ├── models/           # SQLAlchemy 모델
│   │   ├── pipeline/         # RAG 7단계 파이프라인
│   │   ├── tasks/            # Celery 태스크
│   │   └── main.py           # FastAPI 앱 진입점
│   ├── .env                  # 환경 변수 (git 제외)
│   ├── .env.example          # 환경 변수 템플릿
│   └── requirements.txt      # Python 패키지
├── docs/                     # 문서
├── venv/                     # 가상환경 (git 제외)
└── docker-compose.yml        # Docker 설정
```

---

## 🔗 다음 단계

환경 구축 완료 후:

1. **Ingestion 테스트:** Google Drive 폴더 ID로 문서 수집
2. **Pipeline 디버깅:** Celery Worker 로그 확인
3. **Search API 통합:** 팀원과 함께 검색 기능 연결
