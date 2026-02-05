# 📘 Council-AI: 학생회 업무 자동화 및 지식 관리 솔루션

# 1. Project Overview (프로젝트 개요)

> **"복잡한 행정은 AI에게, 학생회는 학우에게 집중하도록."**
> 
- **프로젝트명:** Council-AI (학생회 AI 비서)
- **목표:** Google Workspace 기반의 문서 데이터 파이프라인 구축 및 RAG를 통한 지식 자산화, 업무 자동화.
- **핵심 가치:**
    1. **자산화:** 휘발되는 회의록과 자료를 '검색 가능한 DB'로 영구 저장.
    2. **자동화:** 회의 결과 정리부터 캘린더 등록까지의 수작업 제거.
    3. **연결성:** 별도 앱 설치 없이 기존 Google Docs 환경(Sidebar)에서 즉시 실행.

# 2. Technology Stack (기술 스택 - GCP Edition)

우리는 **Google Cloud Native** 환경을 지향합니다.

| **구분 (Layer)** | **기술 스택 (Stack)** | **상세 설명 및 선정 이유** |
| --- | --- | --- |
| **Frontend** | **Google Apps Script (GAS)** | • 별도의 웹 호스팅 없이 구글 닥스 사이드바 내에서 동작
• HTML/CSS/JS로 UI 구성 |
| **Backend** | **FastAPI (Python)** | • 비동기(`async`) 처리에 최적화
• LangChain, Upstage 등 AI 라이브러리와 호환성 우수 |
| **Infrastructure** | **GCP Compute Engine** | • 인스턴스 타입: `e2-medium` (비용 효율성)
• 배포 방식: Docker & Docker Compose (컨테이너화) |
| **Parsing** | **Upstage Doc Parser API** | • 안건지의 복잡한 표(Table) 구조 인식 및 HTML 변환
• 문서 구조화의 핵심 엔진 |
| **AI Models** | **Gemini 1.5 Flash** | • LLM: 1M Token Context로 긴 회의록 처리
• Vision: 표/차트/이미지 캡셔닝 (가성비 최강) |
| **Storage** | **Google Cloud Storage (GCS)** | • 문서에서 추출된 이미지 원본 저장소
• AWS S3 대체 (Google Client 라이브러리 사용) |
| **Database** | **PostgreSQL + pgvector** | • 정형 데이터(메타정보)와 비정형 데이터(벡터) 통합 관리
• Docker 컨테이너로 GCE 위에서 구동 |
| **Task Queue** | **Celery + Redis** | • 문서 파싱, 임베딩 등 시간이 걸리는 작업의 비동기 처리 |
| **Auth** | **Google Service Account** | • **ADC(Application Default Credentials)** 방식 활용
• JSON 키 파일 관리 최소화로 보안성 강화 |

# 3. Core Features Specification (핵심 기능 명세)

### Feature 1. 회의 자동화 (Smart Minutes)

- **Input:** 안건지(Google Docs ID) + 녹음본/속기록 텍스트
- **Logic:**
    1. Docs API로 안건지 템플릿 로드.
    2. LLM이 속기록을 분석하여 `결정 사항(Decision)`, `액션 아이템(Action Item)` 추출.
    3. 템플릿의 Placeholder를 추출된 내용으로 치환 (`batchUpdate`).
- **Output:** 완성된 결과지 Docs 생성.

### Feature 2. 지능형 지식 DB 구축 (Hybrid RAG) **[Core]**

- **Pipeline:**
    1. **Ingestion:** Google Drive 파일 수집 (`rclone` or API). GCE 내부 `/tmp` 활용.
    2. **Parsing:** Upstage API로 HTML 변환 (표 구조 보존).
    3. **Enrichment:** - 추출된 이미지를 **GCS 버킷**에 업로드.
        - Gemini에게 GCS URL(혹은 바이너리) 제공 -> 캡션 생성 -> 본문 삽입.
    4. **Indexing:** (텍스트 + 이미지 묘사 + 링크 요약) Chunking -> `pgvector` 저장.
- **Search:** 질문 -> 임베딩 -> Cosine Similarity -> LLM 답변.
- **Biz Logic:** '간식', '회식' 키워드 시 제휴 업체 정보 함께 검색.

### Feature 3. 스마트 캘린더 (Shared Calendar)

- **방식:** 공유 캘린더 구독 방식 (팀원이 미리 구독 및 알림 설정 완료 상태)
- **Logic:**
    1. 결과지에서 `[날짜]`, `[담당자]`, `[할일]` 추출.
    2. Service Account가 **공유 캘린더 ID**에 이벤트 생성 (`insert`).
    3. 제목/설명에 담당자 태그 포함.

## 4. 데이터 파이프라인 명세 (Data Pipeline Specification)

가장 중요한 **문서 처리 로직**입니다. Google Drive에서 파일을 가져와 DB에 넣고 정리하는 전체 흐름입니다.

> **인증(Authentication)** 부분에서 JSON 키 파일을 직접 다루던 방식에서, GCE(Google Compute Engine)의 **ADC(Application Default Credentials)**를 활용하는 방식으로 변경되어 보안성과 개발 편의성이 대폭 향상되었습니다.
> 

### 🔄 Data Pipeline Flow (GCP Edition)

### 1. Ingestion (수집)

- **Source:** Google Drive (사용자 지정 폴더).
- **Method:**
    - **초기 구축:** `rclone`을 사용하여 GCE 내부로 대량 동기화 (GCE IAM 권한 기반 인증).
    - **실시간 요청:** `Google Drive API` 활용.
        - *Change:* 인증 시 `service_account.json` 파일을 로드하지 않고, `google.auth.default()`를 사용하여 **GCE 인스턴스 권한(ADC)**을 자동으로 승계받아 처리.
- **Conversion:** Docs/Sheets 등 구글 전용 포맷은 다운로드 시 `.docx`, `.xlsx`로 자동 변환 (MIME Type Export).
- **Destination:** **GCE(Google Compute Engine)** 내부 임시 디렉토리 (`/tmp/ingestion`).

### 2. Parsing (구조화)

- **Tool:** Upstage Document Parser API.
- **Process:** GCE `/tmp`에 있는 파일을 Upstage API로 전송하여 HTML/Markdown 형태의 구조화된 데이터 수신.
- **Extraction:** 문서 내 포함된 이미지(표, 차트, 사진)는 별도 파일로 추출하여 로컬(`image_01.jpg`)에 임시 저장.

### 3. Enrichment (AI 분석)

- **Vision (Storage):**
    - *Change:* 추출된 이미지를 **Google Cloud Storage (GCS)** 버킷에 업로드.
    - *Library:* `google-cloud-storage` 파이썬 클라이언트 사용.
    - *Result:* `gs://council-data/images/...` 형태의 URI 또는 `https://storage.googleapis.com/...` 공개 URL 생성.
- **Captioning:**
    - Gemini 1.5 Flash에게 GCS URI(또는 바이너리)를 전송.
    - **Prompt:** "이 이미지가 표나 조직도라면 마크다운으로 구조를 텍스트화하고, 일반 사진이라면 상황을 상세 묘사해 줘."
- **Merge:** Upstage가 반환한 본문 HTML 내의 `<img>` 태그 위치를 찾아, Gemini가 생성한 **설명 텍스트(Description)**로 치환(Replace).

### 4. Indexing (저장)

- **Chunking:** LangChain 등을 사용하여 의미 단위(Semantic)로 텍스트 분할.
- **Embedding:** 텍스트 청크를 벡터로 변환 (Gemini Embedding Model).
- **DB Insert:** GCE 내 Docker로 구동 중인 **PostgreSQL (pgvector)**에 벡터 및 메타데이터(링크, 페이지 정보 등) 저장.

### 5. Cleanup (정리)

- **Security:** 작업 완료 즉시 GCE `/tmp` 내의 다운로드된 원본 파일 및 추출된 이미지 파일 **영구 삭제** (스토리지 용량 확보 및 보안 유지).