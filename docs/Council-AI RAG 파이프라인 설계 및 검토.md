# **Council-AI: RAG 데이터 파이프라인 아키텍처 기술 명세서**

## **1\. 서론 (Executive Summary)**

본 기술 명세서는 서울대학교 컴퓨터공학부 학생회(이하 '본 조직')의 업무 효율화 및 지식 자산화를 목표로 하는 **Council-AI** 프로젝트의 MVP(Minimum Viable Product) 개발을 위한 심층 기술 보고서이다. 사용자가 제시한 7단계의 데이터 처리 결정 사항(수집, 분류, 파싱, 전처리, 청킹, 메타데이터, 임베딩)을 기반으로, 1주일이라는 제한된 개발 스프린트 내에 구현 가능한 최적의 **RAG(Retrieval-Augmented Generation) 파이프라인**을 설계하는 데 주안점을 두었다.

특히, 본 보고서는 단순한 코드 구현을 넘어 학생회라는 특수 도메인의 \*\*문서 위계(Hierarchy of Authority)\*\*와 **사건 중심(Event-Centric)** 데이터 모델링을 기술적 아키텍처에 반영하였다. 또한, Windows와 macOS가 혼재된 2인 개발팀의 환경을 고려한 역할 분담 전략과 기술적 위험 요소를 사전에 차단하기 위한 전문가적 제언을 포함한다. 이를 통해 '검색'을 넘어선 '맥락 인지형 AI 비서'를 구축하는 것이 본 설계의 핵심 목표이다.1

## ---

**2\. 도메인 분석 및 데이터 전략 (Domain Analysis)**

성공적인 RAG 시스템 구축을 위해서는 기술 스택 선정 이전에 데이터의 본질을 파악해야 한다. 학생회 데이터는 일반적인 기업 문서와 달리 '행사(Event)'를 중심으로 순환하며, 의결기구와 집행기구 간의 명확한 권위 차이가 존재한다.

### **2.1 문서의 권위(Authority)와 진실(Ground Truth)**

RAG 시스템이 환각(Hallucination) 없이 정확한 답변을 제공하기 위해서는 문서 간의 신뢰도 가중치를 설계에 반영해야 한다.

* **결과지(Result Report)의 절대성:** 기획안이나 회의 속기록에 있는 내용은 '예정'이나 '논의'일 뿐이다. '운영위원회 결과지'와 같이 의결기구가 확정한 문서만이 \*\*Ground Truth(진실)\*\*로 취급되어야 한다. 검색 시 결과지 청크(Chunk)에 더 높은 가중치를 부여해야 한다.1  
* **행사 중심의 데이터 군집화:** 학생회의 업무 단위는 파일이 아닌 '행사(예: 새내기 배움터, 축제)'이다. 따라서 파이프라인은 개별 파일을 처리하되, 이를 DB 상에서 하나의 Event ID로 묶어주는 **가상적인 폴더링(Virtual Folder Structure)** 전략이 필수적이다.

### **2.2 안건(Item) 단위의 구조적 특성**

첨부된 안건지 예시1를 분석한 결과, 학생회 문서는 다음과 같은 고유한 구조를 가진다.

* **보고안건 vs 논의안건:** 명확한 헤더(보고안건 1, 논의안건 2)로 구분된다.  
* **담당자 명시:** 각 안건마다 담당자: 부학생회장 임태빈과 같이 책임 소재가 명시된다. 이는 메타데이터 필터링의 핵심 키(Key)가 된다.  
* **복합 데이터:** 텍스트 설명 하단에 표(Table) 형태의 시간표나 예산안이 포함되는 경우가 빈번하다. 이를 단순 텍스트로 추출하면 구조가 깨져 LLM이 이해할 수 없으므로, **HTML 구조 보존**이 기술적 필수 요건이다.1

## ---

**3\. 7단계 RAG 데이터 파이프라인 상세 기술서 및 타당성 평가**

사용자가 제안한 7단계 프로세스에 대한 기술적/도메인적 심층 분석과 구체적인 구현 가이드를 제시한다.

### **Step 1\. 수집 (Ingestion)**

**사용자 결정 사항:**

* Google Drive에 Service Account를 초대하여 rclone으로 GCS에 동기화.  
* Export Formats: .gdoc → .docx, .gsheet → .xlsx 등으로 변환.

**전문가 타당성 평가 및 제언:**

* **타당성(High):** rclone은 클라우드 스토리지 동기화의 사실상 표준(De facto standard)으로, 1주일 MVP 기간 내에 안정적인 파이프라인을 구축하기에 최적의 선택이다. API를 직접 호출하는 것보다 구현 복잡도가 낮고 오류 복구(Retry) 기능이 강력하다.3  
* **기술적 리스크 (Google Forms):** 사용자가 제공한 이미지에서 .gform은 변환 필수 대상으로 언급되었으나, Google Drive API 및 rclone은 설문지(Forms)의 직접적인 다운로드나 .docx 변환을 지원하지 않는다.3  
  * **\[제언 1\]** .gform 파일은 rclone 설정에서 제외(--exclude)하거나, 링크 파일(.html 또는 .webloc) 형태로 메타데이터만 수집해야 한다. 설문 결과 데이터는 이미 연결된 .gsheet로 수집되므로, Form 자체는 '참조 링크'로서의 가치만 가진다.  
* **환경적 제언 (Mac/Windows):** 팀원(Mac)이 수집을 담당하므로, 파일명 인코딩 문제(NFC/NFD)가 발생할 수 있다. rclone 사용 시 \--drive-encoding 옵션을 확인하여 GCS 및 Linux(Docker) 환경에서의 호환성을 확보해야 한다.

### **Step 2\. 파일 분류 (Classification)**

**사용자 결정 사항:**

* Regex로 1차 패턴 추출 후, LLM으로 파일명 기반 2단계 분류(종류/세부).  
* LLM 프롬프트를 통해 파일명 표준화(예: "제38대 학생회...").

**전문가 타당성 평가 및 제언:**

* **타당성(Medium):** 파일명만으로 내용을 유추하는 것은 한계가 있다. 특히 "1차 회의"라는 파일명만으로는 이것이 "국장단 회의"인지 "운영위원회"인지 알 수 없는 경우가 많다.  
* **기술적 제언:**  
  * **경로 기반 추론(Path-based Inference):** 학생회는 폴더 정리가 엄격한 편이다. 파일명뿐만 아니라 \*\*'상위 폴더 경로'\*\*를 LLM 프롬프트에 함께 제공해야 분류 정확도를 획기적으로 높일 수 있다.  
  * **분류 체계(Taxonomy) 구체화:**  
    1. **Level 1 (대분류):** 회의 서류(.gdocs, .pdf 파일 && 회의 관련 서류), 실제 업무 서류(.gsheet, .pptx 등 다른 형식 파일들( \= .gdocs, .pdf 파일 아닌 것), 기타 파일(.gdocs, .pdf 파일 형식 && 회의 관련 서류 아닌 것)  
    2. **Level 2 (세부분류):** 회의서류 \-\> 안건,속기,결과지(파일 이름 기반)  / 실제 업무 서류 \-\> 파일 형식별로 분류 ex\_ form(.html 참조 링크만), 엑셀(.gsheet), PPT 등 / 기타 파일 \-\> 학생회 내부 사업 보고서 양식  등  
  * **LLM 비용 최적화:** 모든 파일에 대해 LLM을 호출하는 것은 비효율적일 수 있다. 정규식으로 처리가 가능한 표준 파일명(예: \[결과\]...)은 Skip하고, 비정형 파일명에 대해서만 LLM을 호출하는 하이브리드 로직을 권장한다.

### **Step 3\. 파싱 (Parsing)**

**사용자 결정 사항:**

* Upstage Document Parse API 활용 (HTML/Markdown 변환).  
* 표, 이미지는 추출하여 Gemini Vision API로 캡셔닝 후 본문 삽입.

**전문가 타당성 평가 및 제언:**

* **타당성(Very High):** 이 프로젝트의 성패를 가르는 가장 중요한 결정이다. 학생회 데이터의 핵심인 '예산안(표)'과 '일정표'를 일반 OCR로 처리하면 데이터가 무의미한 텍스트 나열로 변질된다. Upstage API는 HTML 태그(\<table\>, \<tr\>)를 복원하므로 구조적 정보를 보존하는 데 탁월하다.5  
* **기술적 제언 (좌표 기반 이미지 매핑):**  
  * Upstage API 응답의 elements 배열에는 각 요소(이미지, 표)의 좌표(coordinates)가 포함된다. 단순히 이미지를 추출하는 것이 아니라, 이 **좌표 정보를 활용하여 원본 PDF에서 해당 영역을 정확히 Crop**한 후 Gemini에게 보내야 해상도 저하 없이 정확한 캡셔닝이 가능하다.7  
  * **Gemini 프롬프트 강화:** 표 이미지를 Gemini에게 보낼 때, "이 이미지는 회의 예산안이다. Markdown 포맷으로 변환하라"고 지시하여 텍스트 데이터로 치환(Replace)해야 검색 품질이 향상된다.

### **Step 4\. 청킹 전 전처리 (Preprocessing)**

**사용자 결정 사항:**

* LLM으로 파싱된 파일을 전처리 (예: 안건 종류 \#, 개별 안건 \#\# 마크다운 헤더 정리).

**전문가 타당성 평가 및 제언:**

* **타당성(Low/Risk):** 파싱된 **전체 문서**를 LLM에 넣어 다시 전처리하는 것은 비용과 시간 측면에서 비효율적이며, 컨텍스트 윈도우 제한으로 인해 문서가 잘릴 위험이 있다.  
* **대안 제언 (Regex on HTML):** Upstage가 이미 HTML 구조를 반환한다. LLM을 쓰는 대신, HTML 태그를 기반으로 헤더를 재정립하는 것이 훨씬 빠르고 정확하다.  
  * 예: HTML의 \<h1\>, \<h2\>, 또는 bold \+ 글자 크기 정보를 기반으로 파이썬 스크립트(BeautifulSoup)를 이용해 \# 태그를 붙이는 것이 안전하다. LLM은 이 단계보다는 '분류'나 '메타데이터 추출'과 같은 추론 영역에 사용하는 것이 적절하다.

### **Step 5\. 청킹 전략 (Chunking)**

**사용자 결정 사항:**

* **Parent-Child Chunking:** 안건 덩어리(Parent) \- 개별 문장/문단(Child).  
* Splitter: Markdown Header (\#\#) 기준.

**전문가 타당성 평가 및 제언:**

* **타당성(Very High):** 도메인 지식이 가장 잘 반영된 전략이다. 학생회 문서는 '안건' 단위로 독립적인 문맥을 가지므로, 단순 길이 기반 청킹(Fixed Size Chunking)은 문맥을 파괴한다.1  
* **구현 디테일:**  
  * **Parent Chunk:** 하나의 안건 전체 (예: "논의안건 1\. 축제 가수 섭외" 전체 텍스트 \+ 표). 이는 LLM에게 답변을 위한 **Context**로 제공된다.  
  * **Child Chunk:** Parent를 의미 단위(문단)로 더 잘게 쪼갠 것. 벡터 검색(Embedding)의 대상이 된다.  
  * **Mapping:** DB 테이블에서 parent\_id를 통해 Child가 Parent를 참조하도록 설계해야 한다. 검색은 Child로 하되, 반환은 Parent를 반환하여 LLM이 "가수 섭외 논의의 전체 맥락"을 보고 답변하게 해야 한다.

### **Step 6\. 메타데이터 주입 (Metadata)**

**사용자 결정 사항:**

* 행사명, 파일 종류, 원문 링크, 연도, 날짜, 담당 국서, 관련 파일(Reference).

**전문가 타당성 평가 및 제언:**

* **필수 추가 항목 제언:**  
  1. **authority\_level (권위 레벨):** (1: 일반, 2: 국서/집행부, 3: 의결기구/회장단). 검색 시 가중치 부여용.  
  2. **event\_id (행사 식별자):** 단순 행사명 텍스트가 아닌, events 테이블의 Foreign Key를 부여하여, "24년 축제"와 "25년 축제"를 구분하거나 연결할 수 있어야 한다.  
  3. **time\_decay\_factor:** 문서의 생성일자(created\_at)를 기준으로 최신 정보에 가중치를 주기 위한 날짜 필드가 필수적이다.

### **Step 7\. 임베딩 및 인덱싱 (Embedding)**

**사용자 결정 사항:**

* Vertex AI 임베딩, HNSW 인덱싱.

**전문가 타당성 평가 및 제언:**

* **타당성(High):** Vertex AI(text-embedding-004 등)는 다국어(한국어) 성능이 우수하고 GCP 생태계와 통합이 쉽다.  
* **인덱싱 전략:** pgvector의 **HNSW (Hierarchical Navigable Small Worlds)** 인덱스는 필수적이다. IVFFlat에 비해 인덱스 빌드 시간이 빠르고(데이터 추가 시 재학습 불필요), 검색 속도와 재현율(Recall) 밸런스가 뛰어나 MVP 환경에 적합하다.8

## ---

**4\. RAG 아키텍처 상세 설계 (Roles & Stack)**

### **4.1 역할 분담 최적화 (Optimization)**

사용자(Windows, 도메인 전문가)와 팀원(Mac, 개발 파트너)의 환경을 고려한 최적의 역할 분담이다.

| 단계 | 담당자 | 환경적 고려사항 및 작업 내용 |
| :---- | :---- | :---- |
| **1\. 인프라 구축** | **사용자 (Lead)** | GCP 프로젝트 생성, Service Account 발급, Cloud SQL(PostgreSQL) 생성. Docker Compose 설정 파일 작성 (Windows WSL2 환경 권장). |
| **2\. 수집 (Ingestion)** | **팀원 (Mac)** | Mac 터미널에서 rclone 스크립트 작성 및 테스트. **주의:** 파일명 자소 분리(NFD) 문제를 방지하기 위해 rclone 옵션에 \--drive-encoding 확인 필요. |
| **3\. 분류 & 메타데이터** | **사용자** | 도메인 지식이 필수적이므로, LLM 프롬프트(파일명 표준화, 카테고리 분류) 엔지니어링 수행. |
| **4\. 파싱 & 전처리** | **팀원** | Python 비동기(asyncio) 스크립트로 Upstage API 연동 구현. 이미지 추출 및 Gemini Vision 처리 로직 구현. |
| **5\. DB & 임베딩** | **공동 (User Review)** | 팀원이 DB 연결 로직(SQLAlchemy/SQLModel) 구현, 사용자가 스키마(pgvector, 메타데이터 컬럼) 확정 및 검수. |
| **6\. UI (Apps Script)** | **팀원** | Frontend 경험이 있다면 Apps Script로 Sidebar UI 구현. |

### **4.2 데이터베이스 스키마 제안 (PostgreSQL \+ pgvector)**

Parent-Child 구조와 메타데이터 필터링을 지원하는 최적화된 스키마이다.

SQL

\-- 확장 기능 활성화  
CREATE EXTENSION IF NOT EXISTS vector;

\-- 1\. 행사 (Events) 테이블: 모든 문서의 중심축  
CREATE TABLE events (  
    id SERIAL PRIMARY KEY,  
    name TEXT NOT NULL,              \-- 예: "2025 새내기 배움터"  
    event\_date DATE,                 \-- 행사 진행일 (Time Decay 계산용)  
    category TEXT,                   \-- 예: "복지", "문화"  
    year INTEGER,                    \-- 예: 2025  
    created\_at TIMESTAMP DEFAULT NOW()  
);

\-- 2\. 문서 (Documents) 테이블: 원본 파일 정보  
CREATE TABLE documents (  
    id SERIAL PRIMARY KEY,  
    event\_id INTEGER REFERENCES events(id),  
    title TEXT NOT NULL,             \-- 예: "제6차 국장단회의 결과지"  
    gcs\_url TEXT NOT NULL,           \-- GCS 원본 링크  
    doc\_type TEXT,                   \-- 'agenda'(안건), 'result'(결과), 'minute'(속기)  
    authority\_level INTEGER DEFAULT 1, \-- 1:일반, 2:국장단, 3:운영위 (가중치용)  
    manager TEXT,                    \-- 담당자 (예: "부학생회장 임태빈")  
    upload\_date TIMESTAMP DEFAULT NOW(),  
    raw\_text TEXT                    \-- 전체 텍스트 (Full-text search용 보조)  
);

\-- 3\. 청크 (Chunks) 테이블: 벡터 검색 대상 (Child Chunk)  
CREATE TABLE chunks (  
    id SERIAL PRIMARY KEY,  
    document\_id INTEGER REFERENCES documents(id) ON DELETE CASCADE,  
      
    \-- 내용  
    content TEXT NOT NULL,           \-- Child Chunk (검색용 텍스트)  
    parent\_content TEXT,             \-- Parent Chunk (LLM 제공용 전체 맥락)  
      
    \-- 벡터 (Vertex AI Embedding 차원 수에 맞춤, 예: 768\)  
    embedding vector(768),  
      
    \-- 메타데이터 (필터링 최적화)  
    chunk\_index INTEGER,             \-- 문서 내 순서  
    section\_header TEXT              \-- 예: "논의안건 2\. 컴씨 타임테이블"  
);

\-- 인덱스 설정 (HNSW for speed)  
CREATE INDEX ON chunks USING hnsw (embedding vector\_cosine\_ops);  
CREATE INDEX ON events (event\_date); \-- 시간 감쇠 검색 최적화

## ---

**5\. Mermaid 구조도 및 파이프라인 코드**

아래 다이어그램은 데이터의 흐름과 시스템 구성을 시각화한다.

코드 스니펫

graph TD  
    %% 스타일 정의  
    classDef storage fill:\#e1f5fe,stroke:\#01579b,stroke-width:2px;  
    classDef process fill:\#fff3e0,stroke:\#e65100,stroke-width:2px;  
    classDef ai fill:\#f3e5f5,stroke:\#4a148c,stroke-width:2px;  
    classDef user fill:\#e8f5e9,stroke:\#1b5e20,stroke-width:2px;

    subgraph "1. 수집 및 저장 (Data Lake)"  
        Drive:::storage  
        Rclone:::process  
        GCS\_Raw:::storage  
    end

    subgraph "2. 처리 및 분석 (Processing)"  
        Parser:::ai  
        Classifier:::process  
        Img\_Extract:::process  
        Gemini\[Gemini Vision\<br\>(Captioning)\]:::ai  
        Merger:::process  
    end

    subgraph "3. 인덱싱 및 저장 (Knowledge Base)"  
        Splitter\[Parent-Child Chunking\<br\>(Markdown Header)\]:::process  
        Embedder\[Vertex AI Embedding\]:::ai  
        DB:::storage  
    end

    subgraph "4. 활용 (Service)"  
        User\[학생회 임원\]:::user  
        DocsUI:::user  
        FastAPI:::process  
    end

    %% 데이터 흐름  
    Drive \--\>|Sync / Convert| Rclone  
    Rclone \--\> GCS\_Raw  
    GCS\_Raw \--\> Classifier  
    Classifier \--\>|Typed Files| Parser  
    Parser \--\>|HTML Structure| Img\_Extract  
    Img\_Extract \--\>|Crop Image| Gemini  
    Gemini \--\>|Description| Merger  
    Parser \--\>|Text Content| Merger  
    Merger \--\>|Full Context| Splitter  
    Splitter \--\>|Child Chunks| Embedder  
    Embedder \--\>|Vectors| DB  
    Splitter \--\>|Metadata| DB

    %% 검색 흐름  
    User \--\>|질문 입력| DocsUI  
    DocsUI \--\>|API Call| FastAPI  
    FastAPI \--\>|Hybrid Search| DB  
    DB \--\>|Top-K Context| FastAPI  
    FastAPI \--\>|Generation| User

## ---

**6\. 핵심 로직 상세 구현 가이드**

### **6.1 시간 감쇠(Time Decay) 기반 하이브리드 검색 쿼리**

사용자가 요청한 \*\*"최신 데이터 가중치"\*\*를 구현하기 위해, 단순 코사인 유사도에 시간 감쇠 함수를 결합한 커스텀 스코어링 SQL을 제안한다.1

**수식:** ![][image1]

SQL

SELECT   
    c.content,  
    c.parent\_content,  
    d.title,  
    e.event\_date,  
    \-- 1\. 의미적 유사도 (0\~1)  
    (1 \- (c.embedding \<=\> '')) AS vector\_score,  
    \-- 2\. 최신성 점수 (지수 감쇠: 1년 지나면 점수 급감)  
    EXP(\-0.001 \* EXTRACT(DAY FROM NOW() \- e.event\_date)) AS time\_score  
FROM chunks c  
JOIN documents d ON c.document\_id \= d.id  
JOIN events e ON d.event\_id \= e.id  
WHERE   
    \-- 메타데이터 필터링 (권한 및 연도)  
    d.authority\_level \>= 1   
ORDER BY   
    \-- 가중 합산 점수로 정렬  
    ((1 \- (c.embedding \<=\> '')) \* 0.7 \+   
     (EXP(\-0.001 \* EXTRACT(DAY FROM NOW() \- e.event\_date)) \* 0.3)) DESC  
LIMIT 5;

### **6.2 Google Forms 처리 전략 (예외 처리)**

rclone 로그 분석 결과 application/vnd.google-apps.form 포맷은 내보내기 오류를 발생시킨다.4 이를 해결하기 위한 전략은 다음과 같다.

1. **Skip & Link:** rclone 실행 시 \--exclude "\*.gform" 옵션으로 파일 동기화에서 제외한다.  
2. **Metadata Only:** 별도의 Python 스크립트(Google Drive API)를 통해 Form 파일의 webViewLink만 추출하여, RAG 검색 시 "참가자 명단은 아래 링크에서 확인하세요"라고 답변할 수 있도록 **Reference 테이블**에 저장한다.

## ---

**7\. 결론 및 MVP 개발 전략**

Council-AI 프로젝트는 학생회 업무의 \*\*'맥락(Context)'\*\*을 보존하는 것이 핵심이다. 본 기술서는 Upstage의 구조 인식 능력과 Parent-Child Chunking을 결합하여, 단순한 단어 매칭이 아닌 \*\*'안건 단위의 지식 검색'\*\*을 가능하게 설계되었다.

**1주일 MVP 성공을 위한 최우선 순위:**

1. **자동 분류 포기, 폴더 구조화 집중:** LLM 기반 자동 분류기를 완벽하게 짜는 것보다, Google Drive의 폴더 구조(2025/1학기/국장단회의)를 사람이 미리 정리하고 rclone으로 경로 정보를 메타데이터로 쓰는 것이 훨씬 효율적이다.  
2. **HTML 파싱의 완결성:** Upstage API가 반환하는 HTML을 Markdown으로 섣불리 변환하지 말고, HTML 태그(\<h2\>, \<table\>)를 기준으로 청킹하는 로직에 집중해야 한다. 이것이 예산안 표를 살리는 길이다.  
3. **역할의 명확화:** 사용자(Lead)는 DB 스키마와 검색 로직(SQL)에 집중하고, 팀원은 데이터 파이프라인(rclone, Parsing) 스크립트 작성에 집중하여 병렬로 개발을 진행해야 한다.

이 설계서는 Council-AI가 단순한 장난감 프로젝트를 넘어, 실제 학생회 업무를 혁신하는 실용적인 도구로 기능하기 위한 견고한 토대가 될 것이다.

#### **참고 자료**

1. Council-AI RAG 설계 및 개발 가이드.pdf  
2. Upstage Document Parse, 1월 30, 2026에 액세스, [https://www.upstage.ai/products/document-parse](https://www.upstage.ai/products/document-parse)  
3. Google drive \- Rclone, 1월 30, 2026에 액세스, [https://rclone.org/drive/](https://rclone.org/drive/)  
4. Move files on from Google Drive to Google Drive \- Help and Support \- rclone forum, 1월 30, 2026에 액세스, [https://forum.rclone.org/t/move-files-on-from-google-drive-to-google-drive/31722](https://forum.rclone.org/t/move-files-on-from-google-drive-to-google-drive/31722)  
5. Upstage Document Parse: Let LLMs read your documents with speed and accuracy, 1월 30, 2026에 액세스, [https://www.upstage.ai/blog/en/let-llms-read-your-documents-with-speed-and-accuracy](https://www.upstage.ai/blog/en/let-llms-read-your-documents-with-speed-and-accuracy)  
6. Benchmarking the Most Reliable Document Parsing API | by Sarah Guthals, PhD | Tensorlake AI | Medium, 1월 30, 2026에 액세스, [https://medium.com/tensorlake-ai/benchmarking-the-most-reliable-document-parsing-api-b8065686daff](https://medium.com/tensorlake-ai/benchmarking-the-most-reliable-document-parsing-api-b8065686daff)  
7. langchain\_upstage.document\_parse\_parsers — LangChain documentation \- AiDocZh, 1월 30, 2026에 액세스, [https://aidoczh.com/langchain/api\_reference/\_modules/langchain\_upstage/document\_parse\_parsers.html](https://aidoczh.com/langchain/api_reference/_modules/langchain_upstage/document_parse_parsers.html)  
8. Faster similarity search performance with pgvector indexes | Google Cloud Blog, 1월 30, 2026에 액세스, [https://cloud.google.com/blog/products/databases/faster-similarity-search-performance-with-pgvector-indexes](https://cloud.google.com/blog/products/databases/faster-similarity-search-performance-with-pgvector-indexes)  
9. Refining Vector Search Queries With Time Filters in Pgvector: A Tutorial \- Tiger Data, 1월 30, 2026에 액세스, [https://www.tigerdata.com/blog/refining-vector-search-queries-with-time-filters-in-pgvector-a-tutorial](https://www.tigerdata.com/blog/refining-vector-search-queries-with-time-filters-in-pgvector-a-tutorial)

[image1]: <data:image/png;base64,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>