# Council-AI

> 학생회 업무 자동화 및 지식 관리 솔루션

복잡한 행정은 AI에게, 학생회는 학우에게 집중하도록.

## 목차

- [프로젝트 개요](#프로젝트-개요)
- [기술 스택](#기술-스택)
- [프로젝트 구조](#프로젝트-구조)
- [설치 및 실행](#설치-및-실행)
- [API 문서](#api-문서)
- [개발 가이드](#개발-가이드)

---

## 프로젝트 개요

Council-AI는 Google Workspace 기반의 문서 데이터 파이프라인을 구축하고, RAG(Retrieval-Augmented Generation)를 통해 학생회의 지식을 자산화하며, 반복적인 업무를 자동화하는 솔루션입니다.

### 핵심 기능

| 기능 | 설명 |
|------|------|
| **회의 자동화** | 안건지 + 속기록 → AI가 결정사항/액션아이템 추출 → 결과지 자동 생성 |
| **지능형 지식 DB** | 문서 수집 → 파싱 → 임베딩 → 벡터 검색 → LLM 답변 생성 |
| **스마트 캘린더** | 문서에서 일정 정보 추출 → Google Calendar 자동 등록 |

---

## 기술 스택

| 구분 | 기술 |
|------|------|
| Frontend | Google Apps Script (Sidebar Add-on) |
| Backend | FastAPI (Python 3.11) |
| Database | PostgreSQL 16 + pgvector |
| Task Queue | Celery + Redis |
| AI | Gemini 1.5 Flash, Gemini Embedding |
| Document Parsing | Upstage Document Parse API |
| Cloud Storage | Google Cloud Storage |
| Infrastructure | Docker, Docker Compose |

---

## 프로젝트 구조

```
week4/
├── README.md                 # 프로젝트 설명서 (현재 파일)
├── CLAUDE.md                 # AI 개발 지침서
├── docker-compose.yml        # Docker 서비스 구성
├── .env.example              # 환경변수 템플릿
├── .gitignore                # Git 제외 파일 목록
│
├── backend/                  # FastAPI 백엔드
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── pyproject.toml
│   ├── app/
│   │   ├── main.py
│   │   ├── core/
│   │   ├── api/
│   │   ├── models/
│   │   ├── schemas/
│   │   ├── services/
│   │   └── tasks/
│   └── tests/
│
└── frontend/                 # Google Apps Script
    ├── appsscript.json
    ├── clasp.json
    └── src/
```

---

## 상세 디렉토리 설명

### 루트 파일

| 파일 | 설명 |
|------|------|
| `docker-compose.yml` | PostgreSQL, Redis, Backend, Celery Worker 컨테이너 정의 |
| `.env.example` | 환경변수 템플릿. `.env`로 복사 후 실제 값 설정 |
| `.gitignore` | 버전 관리 제외 파일 (credentials, venv, __pycache__ 등) |
| `CLAUDE.md` | AI 페어 프로그래밍을 위한 프로젝트 컨텍스트 및 개발 규칙 |

---

### Backend 구조

#### `backend/` - FastAPI 백엔드 애플리케이션

```
backend/
├── Dockerfile              # 컨테이너 이미지 빌드 설정
├── requirements.txt        # Python 의존성 패키지 목록
├── pyproject.toml          # 프로젝트 메타데이터 및 도구 설정
│
├── app/                    # 애플리케이션 소스 코드
│   ├── __init__.py         # 패키지 초기화, 버전 정보
│   ├── main.py             # FastAPI 앱 진입점, 라우터 등록
│   │
│   ├── core/               # 핵심 설정 및 유틸리티
│   │   ├── __init__.py
│   │   ├── config.py       # Pydantic Settings 기반 환경설정
│   │   ├── database.py     # asyncpg 연결 풀, pgvector 초기화
│   │   └── security.py     # Google ADC 인증, API 키 검증
│   │
│   ├── api/                # API 엔드포인트
│   │   ├── __init__.py
│   │   ├── deps.py         # 의존성 주입 (DB 세션, 인증 등)
│   │   └── v1/             # API 버전 1
│   │       ├── __init__.py
│   │       ├── router.py   # 라우터 통합
│   │       ├── minutes.py  # 회의록 자동화 API
│   │       ├── rag.py      # RAG 검색 API
│   │       └── calendar.py # 캘린더 API
│   │
│   ├── models/             # SQLAlchemy ORM 모델
│   │   ├── __init__.py
│   │   ├── base.py         # DeclarativeBase, TimestampMixin
│   │   ├── document.py     # 문서 메타데이터 모델
│   │   └── embedding.py    # 벡터 임베딩 청크 모델 (pgvector)
│   │
│   ├── schemas/            # Pydantic 요청/응답 스키마
│   │   ├── __init__.py
│   │   ├── minutes.py      # 회의록 관련 스키마
│   │   ├── rag.py          # RAG 검색 관련 스키마
│   │   └── calendar.py     # 캘린더 관련 스키마
│   │
│   ├── services/           # 비즈니스 로직 서비스
│   │   ├── __init__.py
│   │   ├── google/         # Google API 서비스
│   │   │   ├── drive.py    # Drive 파일 목록/다운로드/업로드
│   │   │   ├── docs.py     # Docs 읽기/쓰기/batchUpdate
│   │   │   ├── sheets.py   # Sheets 범위 읽기/쓰기
│   │   │   ├── calendar.py # Calendar 이벤트 CRUD
│   │   │   └── storage.py  # GCS 버킷 업로드/다운로드
│   │   ├── ai/             # AI 서비스
│   │   │   ├── gemini.py   # Gemini LLM (텍스트/Vision)
│   │   │   └── embeddings.py # 텍스트 임베딩 생성
│   │   ├── parser/         # 문서 파싱 서비스
│   │   │   └── upstage.py  # Upstage Document Parse API
│   │   └── rag/            # RAG 파이프라인
│   │       ├── chunker.py  # 텍스트 청킹 (LangChain)
│   │       ├── retriever.py # pgvector 벡터 검색
│   │       └── pipeline.py # 전체 RAG 파이프라인
│   │
│   └── tasks/              # Celery 비동기 작업
│       ├── __init__.py
│       ├── celery_app.py   # Celery 앱 설정
│       └── document.py     # 문서 처리 태스크
│
└── tests/                  # 테스트 코드
    ├── __init__.py
    ├── conftest.py         # pytest 공통 fixture
    └── test_api/           # API 엔드포인트 테스트
        ├── test_health.py
        ├── test_minutes.py
        ├── test_rag.py
        └── test_calendar.py
```

#### Core 모듈 상세

| 파일 | 역할 |
|------|------|
| `config.py` | 환경변수 로드 (DATABASE_URL, API 키 등), 설정 검증 |
| `database.py` | PostgreSQL 비동기 연결, pgvector 확장 활성화, 세션 팩토리 |
| `security.py` | Google ADC 인증, Service Account 토큰 관리 |

#### API 엔드포인트 상세

| 엔드포인트 | 메서드 | 설명 |
|------------|--------|------|
| `/api/v1/minutes/process` | POST | 회의록 처리 요청 (비동기) |
| `/api/v1/minutes/{id}/status` | GET | 처리 상태 조회 |
| `/api/v1/rag/ingest` | POST | 폴더 문서 수집 요청 |
| `/api/v1/rag/search` | POST | 벡터 검색 + LLM 답변 생성 |
| `/api/v1/rag/documents` | GET | 인덱싱된 문서 목록 |
| `/api/v1/calendar/events` | POST | 캘린더 이벤트 생성 |
| `/api/v1/calendar/events` | GET | 이벤트 목록 조회 |

#### 서비스 레이어 상세

| 서비스 | 역할 |
|--------|------|
| `GoogleDriveService` | 파일 목록 조회, 다운로드, Google 문서 → docx/xlsx 변환 |
| `GoogleDocsService` | 문서 읽기, 템플릿 복사, 플레이스홀더 치환 |
| `GoogleSheetsService` | 스프레드시트 범위 읽기/쓰기, 행 추가 |
| `GoogleCalendarService` | 이벤트 CRUD, 시간 범위 조회 |
| `GoogleStorageService` | GCS 버킷 파일 업로드/다운로드, Signed URL 생성 |
| `GeminiService` | 텍스트 생성, 이미지 캡셔닝, 회의록 분석 |
| `EmbeddingService` | 텍스트 → 768차원 벡터 변환 |
| `UpstageDocParser` | PDF/DOCX → HTML/Markdown 구조화 파싱 |
| `TextChunker` | 시맨틱 단위 텍스트 분할 |
| `VectorRetriever` | pgvector 코사인 유사도 검색 |
| `RAGPipeline` | 수집 → 파싱 → 임베딩 → 검색 전체 워크플로우 |

---

### Frontend 구조

#### `frontend/` - Google Apps Script 애드온

```
frontend/
├── appsscript.json         # GAS 매니페스트 (권한, 런타임 설정)
├── clasp.json              # clasp CLI 설정 (로컬 개발용)
│
└── src/                    # 소스 코드
    ├── Code.gs             # 서버 사이드 스크립트
    ├── Sidebar.html        # 사이드바 UI 레이아웃
    ├── Styles.html         # CSS 스타일시트
    └── Scripts.html        # 클라이언트 JavaScript
```

#### Frontend 파일 상세

| 파일 | 역할 |
|------|------|
| `appsscript.json` | OAuth 스코프, Advanced Services (Drive, Docs, Calendar) 설정 |
| `clasp.json` | Script ID 매핑, 로컬 push/pull 설정 |
| `Code.gs` | `onOpen()` 메뉴 추가, `showSidebar()`, Backend API 호출 함수 |
| `Sidebar.html` | 탭 기반 UI (회의록 / 검색 / 일정), 결과 표시 영역 |
| `Styles.html` | Material Design 스타일, 반응형 레이아웃 |
| `Scripts.html` | 탭 전환, API 호출, 로딩/토스트 UI, 상태 폴링 |

---

## 설치 및 실행

### 1. 환경 설정

```bash
# 환경변수 파일 생성
cp .env.example .env

# .env 파일 편집 (실제 값 입력)
# - GEMINI_API_KEY
# - UPSTAGE_API_KEY
# - GOOGLE_CLOUD_PROJECT
# - GOOGLE_APPLICATION_CREDENTIALS
```

### 2. Docker로 실행

```bash
# 전체 서비스 시작
docker-compose up -d

# 로그 확인
docker-compose logs -f backend

# 서비스 중지
docker-compose down
```

### 3. 로컬 개발 (Backend)

```bash
cd backend

# 가상환경 생성
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# 의존성 설치
pip install -r requirements.txt

# 개발 서버 실행
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### 4. Frontend 배포 (GAS)

```bash
cd frontend

# clasp 설치 (최초 1회)
npm install -g @google/clasp

# Google 로그인
clasp login

# 새 스크립트 생성 또는 기존 스크립트 연결
clasp create --title "Council-AI" --type docs

# 코드 배포
clasp push

# 웹 에디터 열기
clasp open
```

---

## API 문서

서버 실행 후 아래 URL에서 API 문서를 확인할 수 있습니다:

- **Swagger UI**: http://localhost:8000/docs
- **ReDoc**: http://localhost:8000/redoc
- **OpenAPI JSON**: http://localhost:8000/api/v1/openapi.json

### 헬스 체크

```bash
curl http://localhost:8000/health
# {"status": "healthy"}
```

---

## 개발 가이드

### 테스트 실행

```bash
cd backend

# 전체 테스트
pytest

# 커버리지 포함
pytest --cov=app --cov-report=html

# 특정 테스트
pytest tests/test_api/test_health.py -v
```

### 코드 스타일

```bash
# Ruff 린터
ruff check app/

# MyPy 타입 체크
mypy app/
```

### 데이터베이스 마이그레이션

```bash
# Alembic 마이그레이션 생성
alembic revision --autogenerate -m "Add new column"

# 마이그레이션 적용
alembic upgrade head
```

---

## 데이터 흐름

### 문서 수집 파이프라인

```
Google Drive → Download/Export → Upstage Parse → Image Caption (Gemini)
                                      ↓
                              Text Chunking (LangChain)
                                      ↓
                              Embedding (Gemini)
                                      ↓
                              PostgreSQL + pgvector
```

### RAG 검색 파이프라인

```
User Query → Embedding → Vector Search (pgvector) → Context Retrieval
                                                          ↓
                              Partner Keywords Check → LLM Answer (Gemini)
                                                          ↓
                                                    Response + Sources
```

### 회의록 자동화

```
Agenda Doc + Transcript → LLM Analysis → Extract Decisions/Actions
                                              ↓
                         Template Copy → Placeholder Replace → Result Doc
```

---

## 라이선스

MIT License

---

## 기여 방법

1. Fork 후 feature 브랜치 생성
2. 변경사항 커밋 (TDD 준수)
3. Pull Request 생성
4. 코드 리뷰 후 머지
