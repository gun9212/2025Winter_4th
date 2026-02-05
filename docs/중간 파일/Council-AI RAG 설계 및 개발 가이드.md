# **Council-AI: RAG 설계 및 개발 가이드(참고용)**

## **1\. 서론 (Introduction)**

본 보고서는 서울대학교 컴퓨터공학부 학생회(이하 '본 조직')의 업무 효율화 및 지식 자산화를 목표로 하는 **Council-AI** 프로젝트의 기술적, 구조적 토대를 마련하기 위해 작성되었다. 1주일이라는 제한된 MVP(Minimum Viable Product) 개발 기간 내에 실질적인 가치를 창출하기 위해서는 단순한 LLM(Large Language Model)의 도입을 넘어, 본 조직의 특수한 도메인 지식(Domain Knowledge)을 시스템 아키텍처에 깊이 있게 투영해야 한다.

특히 본 프로젝트의 핵심인 RAG(Retrieval-Augmented Generation) 시스템은 학생회라는 조직이 생산하는 비정형 문서(회의록, 안건지, 결과지)와 정형 데이터(예산안, 명부)를 유기적으로 연결하여, '검색'을 넘어선 '지능형 비서' 역할을 수행해야 한다. 이를 위해 본 보고서는 학생회 고유의 문서 구조와 업무 흐름을 분석하여 \*\*'학생회 서류 구조 명세서'\*\*를 정의하고, 이를 기반으로 \*\*'GCP 기반 Hybrid RAG 아키텍처'\*\*를 상세히 설계한다. 또한, 개발자가 이해해야 할 핵심 RAG 기술 개념과 구체적인 구현 가이드를 포함하여, 성공적인 MVP 개발을 위한 나침반 역할을 수행하고자 한다.

## ---

**2\. 도메인 분석: 학생회 조직 및 문서 구조 명세 (Domain Specification)**

성공적인 RAG 구축의 첫 단추는 데이터에 대한 완벽한 이해이다. 학생회의 업무는 '행사(Event)'를 중심으로 순환하며, 의결기구와 집행기구 간의 유기적인 문서 흐름을 통해 구체화된다.1

### **2.1 조직 구조와 의사결정 체계 (Organizational Hierarchy)**

문서의 권위(Authority)와 검색 우선순위를 결정하기 위해 조직 구조에 대한 이해가 선행되어야 한다. 학생회칙 및 인수인계서에 따르면, 본 조직은 다음과 같은 위계 구조를 가진다.1

| 조직 구분 | 구성 및 역할 | RAG 데이터 관점의 의미 |
| :---- | :---- | :---- |
| **학생회장단 (Presidency)** | 학생회장, 부학생회장. 집행위원회를 직접 총괄하며, 대내외적인 최종 의사결정권과 대표성을 가짐. | 최상위 정책 결정 문서 생성. 집행부 문서보다 상위의 \*\*'진실(Ground Truth)'\*\*로 간주됨. |
| **의결기구 (Deliberative)** | **운영위원회(Steering Committee)**, 학생총회. 사업 계획 및 예산 승인, 회칙 개정 등 입법적 기능 수행. | 회의 결과지(Result Report)는 \*\*'확정된 사실'\*\*을 담고 있어 가장 높은 신뢰도 가중치를 부여해야 함. |
| **집행기구 (Executive)** | **집행위원회(Executive Committee)**. 국장단(문화, 복지, 기획 등)을 중심으로 실제 행사를 기획하고 수행. | 가장 많은 양의 세부 데이터(기획안, 실무 문서) 생성. 구체적인 실행 맥락(Context)을 제공. |
| **독립기구 (Independent)** | 선거관리위원회 등. 특수 목적을 위해 한시적 또는 독립적으로 운영. | 특정 기간(선거 기간)에만 유효한 데이터를 생성하므로 시계열 필터링이 중요. |

**설계 시사점:** RAG 시스템은 문서의 출처(Author)를 메타데이터로 관리해야 한다. 예를 들어, 문화국의 '간식행사 기획안'과 운영위원회의 '간식행사 결과지' 내용이 충돌할 경우, 운영위원회의 결과지가 최종 승인된 정보로서 우선권을 가져야 한다.1

### **2.2 지식의 기본 단위: '행사(Event)'와 문서 생애주기**

일반적인 기업 데이터와 달리, 학생회 데이터는 \*\*'행사(Event)'\*\*라는 논리적 단위로 강력하게 결합되어 있다. 단일 문서를 독립적으로 처리하는 것은 문맥을 파괴할 위험이 크다.1

#### **2.2.1 문서 생애주기(Lifecycle)에 따른 분류**

하나의 행사는 기획부터 결과 보고까지 일련의 과정을 거치며, 각 단계마다 성격이 다른 문서가 생성된다.

1. **기획 단계 (Planning):**  
   * **문서:** 사업 기획안 (Draft/Plan)  
   * **내용:** 행사의 목적, 예상 예산, 타임라인, R\&R(업무 분장).  
   * **RAG 역할:** 행사의 '의도'와 '초기 설계' 정보를 제공. 사용자가 "원래 기획 의도가 무엇이었나?"라고 물었을 때 참조됨.  
2. **논의 및 의결 단계 (Deliberation):**  
   * **문서:** **안건지 (Agenda)** 1  
   * **내용:** 회의 일시, 참석자, 논의할 주제들의 목록.  
   * **RAG 역할:** 회의의 구조(Structure)를 제공. 어떤 맥락에서 해당 안건이 논의되었는지 파악하는 기준점이 됨.  
3. **실행 및 기록 단계 (Execution & Recording):**  
   * **문서:** **속기록 (Minutes)** 1  
   * **내용:** 발언 내용, 논쟁 과정, 수정 사항의 구체적 사유.  
   * **RAG 역할:** '맥락(Context)'과 '이유(Why)'를 제공. "왜 예산이 삭감되었는가?"와 같은 정성적 질문에 답하기 위한 핵심 자료.  
4. **확정 및 보고 단계 (Confirmation):**  
   * **문서:** **결과지 (Result Report)** 1  
   * **내용:** 최종 결정 사항, 확정된 예산, 승인 여부. 표(Table) 형태로 정리된 경우가 많음.  
   * **RAG 역할:** \*\*'팩트(Fact)'\*\*의 원천. "최종 예산은 얼마인가?"라는 질문에 대해 가장 높은 가중치로 답변해야 함.

#### **2.2.2 안건(Agenda Item) 중심의 데이터 구조화**

학생회 문서는 파일 단위보다 **'안건(Item)'** 단위가 의미론적으로 중요하다. 예를 들어, '제5차 운영위원회 결과지'라는 하나의 파일 안에는 '1. 간식행사 예산 심의', '2. 축제 날짜 변경', '3. 과방 청소 계획' 등 서로 다른 주제의 안건들이 포함되어 있다.1

* **문제점:** 파일 전체를 하나의 덩어리로 처리하거나, 단순히 페이지 단위로 자르면 여러 안건이 섞여 검색 정확도가 떨어진다.  
* **해결책:** 파싱 단계에서 '안건' 헤더(예: "논의안건 1")를 기준으로 문서를 논리적으로 분할(Segmentation)해야 한다. 이렇게 분할된 각 안건 청크는 상위 개념인 '행사(Event)' 태그와 연결되어야 한다.2

### **2.3 민감 정보 및 참조 파일 처리 전략 (Privacy & Reference)**

실제 업무 서류(참가 신청 구글폼, 학생회비 납부 명단 엑셀 등)는 개인정보(PII)를 포함하고 있어 RAG 벡터 DB에 직접 임베딩해서는 안 된다.1

* **참조(Reference) 전략:** 해당 파일들은 텍스트 내용을 임베딩하는 대신, \*\*메타데이터(파일명, 관련 행사, 링크)\*\*만 인덱싱한다.  
* **검색 시나리오:** 사용자가 "이번 간식행사 참가자 명단 어디 있어?"라고 물으면, LLM은 명단 내용을 출력하는 것이 아니라, 해당 파일의 \*\*보안 링크(Google Drive/GCS URL)\*\*를 제공하여 권한이 있는 사용자만 접근하도록 유도한다.4

## ---

**3\. RAG 핵심 기술 심층 분석 (Educational Guide)**

본 섹션은 RAG 및 딥러닝 전문가로서, Council-AI 프로젝트 수행을 위해 필수적인 RAG 심화 기술을 설명한다. 이는 단순한 개념 설명을 넘어, 본 프로젝트의 데이터 특성에 최적화된 기술적 의사결정의 근거를 제공한다.

### **3.1 청킹 전략: Parent-Child Chunking (Hierarchical Chunking)**

사용자가 질문한 "Chunk의 개념과 위계 구조"에 대한 최적의 해답은 **Parent-Child Chunking**이다.2

* **기본 개념:** 문서를 고정된 길이(예: 500 토큰)로 자르는 단순 청킹(Naive Chunking)은 문맥을 단절시킨다. 반면, Parent-Child 방식은 데이터를 두 가지 계층으로 관리한다.  
  * **Parent Chunk:** 문서의 논리적 완결성을 가진 큰 단위 (예: '안건 1\. 간식행사 결과' 전체). 문맥 정보를 온전히 담고 있다.  
  * **Child Chunk:** Parent를 잘게 쪼갠 작은 단위 (예: 그 안의 특정 문단이나 문장). 벡터 검색의 정확도를 높이기 위해 사용된다.  
* **작동 원리:**  
  1. 검색 시, 사용자의 질문 벡터는 작고 구체적인 **Child Chunk**와 매칭된다 (정확도 상승).  
  2. 하지만 LLM에게 정보를 전달할 때는 해당 Child만 주는 것이 아니라, 연결된 **Parent Chunk** 전체를 제공한다 (문맥 보존).  
* **Council-AI 적용:**  
  * *Parent:* 개별 '안건(Agenda Item)' 텍스트 전체.  
  * *Child:* 안건 내의 각 문단, 결정 사항 항목.  
  * *효과:* "간식행사 예산 얼마야?"라는 질문에 "50만 원입니다"라는 문장(Child)을 찾고, 이를 포함한 전체 안건(Parent)을 가져와 "원래 60만 원이었으나 마케팅비를 줄여 50만 원으로 확정되었습니다"라고 답변할 수 있게 된다.

### **3.2 벡터 인덱싱: HNSW vs. IVFFlat**

PostgreSQL의 pgvector 확장은 다양한 인덱싱 알고리즘을 지원한다. 본 프로젝트에서는 **HNSW**를 강력히 권장한다.9

* **IVFFlat (Inverted File Flat):**  
  * 데이터를 클러스터(Cluster)로 묶어 관리한다. 검색 속도는 빠르지만, 클러스터의 중심점(Centroid)을 잡기 위해 데이터가 어느 정도 쌓인 후 **'학습(Training)'** 과정이 필요하다.  
  * 데이터 분포가 바뀌면 재학습해야 하므로, 수시로 문서가 추가되는 환경에는 부적합할 수 있다.  
* **HNSW (Hierarchical Navigable Small Worlds):**  
  * 데이터를 다층 그래프(Layered Graph) 구조로 연결한다. 상위 레이어는 고속도로처럼 넓은 범위를 탐색하고, 하위 레이어로 갈수록 정밀하게 탐색한다.  
  * **장점:** 별도의 학습 과정이 필요 없고, 데이터가 추가되는 즉시 실시간 인덱싱이 가능하다. 검색 정확도(Recall)와 속도 면에서 현재 가장 우수한 알고리즘 중 하나이다.  
  * **단점:** 메모리 사용량이 다소 높으나, e2-medium 인스턴스에서 수천\~수만 건의 학생회 문서를 처리하기에는 충분하다.

### **3.3 Upstage 파서와 HTML 구조의 중요성**

Upstage Document Parser API가 반환하는 HTML 포맷은 RAG 성능의 핵심인 \*\*'구조 인식(Layout Analysis)'\*\*을 가능케 한다.11

* **HTML의 가치:** 일반적인 OCR은 문서를 단순한 텍스트의 나열로 변환하여 표(Table) 구조를 무너뜨린다. 반면, Upstage는 표를 \<table\>, \<tr\>, \<td\> 태그로 완벽하게 복원한다.  
* **LLM과의 호환성:** Gemini와 같은 최신 LLM은 방대한 웹 데이터로 학습되었기 때문에 HTML 구조를 매우 잘 이해한다. HTML로 된 예산안 표를 입력받으면, 모델은 "3열 2행의 숫자가 무엇을 의미하는지" 정확히 파악할 수 있다.13  
* **JSON 응답 구조:** Upstage API는 단순 HTML뿐만 아니라, elements라는 JSON 배열을 반환한다. 여기에는 각 요소(헤더, 문단, 표, 이미지)의 좌표와 타입 정보가 포함되어 있어, 개발자가 "표만 추출"하거나 "헤더를 기준으로 청킹"하는 등의 정교한 후처리를 할 수 있게 해준다.14

### **3.4 메타데이터 필터링 (Metadata Filtering)**

벡터 유사도 검색(Semantic Search)만으로는 한계가 있다. "2024년도 예산안 보여줘"라는 질문에 2023년도 문서를 가져오는 것을 방지하기 위해 **메타데이터 필터링**이 필수적이다.4

* **Pre-filtering:** 벡터 검색을 수행하기 *전*에 SQL의 WHERE 절을 사용하여 검색 범위를 좁히는 방식이다.  
  * WHERE year \= 2024 AND category \= 'Budget'  
* **구현:** 문서 파싱 시 파일 경로(2024/운영위원회/)나 파일명에서 연도, 부서, 문서 타입 등의 메타데이터를 추출하여 DB의 별도 컬럼에 저장해야 한다.1

## ---

**4\. Council-AI 상세 RAG 아키텍처 설계 (Detailed Design)**

이 섹션에서는 앞서 분석한 도메인 지식과 기술 요소를 결합하여, 실제 구현 가능한 시스템 아키텍처를 제시한다.

### **4.1 데이터베이스 스키마 설계 (PostgreSQL \+ pgvector)**

Parent-Child 구조와 메타데이터 필터링, 그리고 개인정보 보호를 지원하기 위한 스키마는 다음과 같다.

SQL

\-- 1\. 행사 (Events) 테이블: 지식의 최상위 논리 단위  
CREATE TABLE events (  
    id SERIAL PRIMARY KEY,  
    title TEXT NOT NULL,             \-- 예: "2025 새내기 배움터"  
    event\_date DATE,                 \-- 행사 실제 진행일 (Time Decay 계산용)  
    category TEXT,                   \-- 예: "문화국", "복지국"  
    year INTEGER,                    \-- 예: 2025  
    status TEXT                      \-- 예: "완료", "기획중"  
);

\-- 2\. 문서 (Documents) 테이블: 원본 파일 메타데이터  
CREATE TABLE documents (  
    id SERIAL PRIMARY KEY,  
    event\_id INTEGER REFERENCES events(id),  
    title TEXT NOT NULL,             \-- 예: "5차 운영위 결과지.pdf"  
    doc\_type TEXT,                   \-- 'agenda'(안건), 'result'(결과), 'minute'(속기), 'reference'(참조)  
    gcs\_url TEXT,                    \-- Google Cloud Storage 원본 링크  
    upload\_date TIMESTAMP DEFAULT NOW()  
);

\-- 3\. 청크 (Chunks) 테이블: 벡터 검색의 대상 (Child Chunk)  
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE chunks (  
    id SERIAL PRIMARY KEY,  
    document\_id INTEGER REFERENCES documents(id),  
    content TEXT NOT NULL,           \-- 실제 텍스트 또는 Markdown 내용  
    parent\_content TEXT,             \-- 상위 문맥(안건 전체) 내용 (Parent Chunk)  
    embedding vector(768),           \-- Gemini Embedding 차원 수  
    chunk\_index INTEGER,             \-- 문서 내 순서 (정렬용)  
    metadata JSONB                   \-- 추가 정보: {page\_num: 1, section: "보고안건 1"}  
);

\-- 4\. 참조 자료 (References) 테이블: 개인정보 보호용 (벡터화 하지 않음)  
CREATE TABLE references (  
    id SERIAL PRIMARY KEY,  
    event\_id INTEGER REFERENCES events(id),  
    description TEXT,                \-- 예: "2025 신입생 명단 파일"  
    file\_link TEXT                   \-- 보안 처리된 드라이브 링크  
);

### **4.2 시간 감쇠(Time-Decay) 기반 하이브리드 검색 로직**

사용자가 요청한 "최신 데이터 가중치" 기능을 구현하기 위해, 단순 코사인 유사도에 **시간 감쇠 함수**를 결합한 커스텀 스코어링을 적용한다.16

**수식:**

**![][image1]**  
여기서 Recency Score는 지수 감쇠(Exponential Decay) 함수를 사용하여, 시간이 지날수록 점수가 급격히 떨어지다가 완만해지도록 설계한다.

**SQL 구현 예시:**

SQL

SELECT   
    c.content,  
    c.parent\_content,  
    d.title,  
    e.event\_date,  
    \-- 1\. 의미적 유사도 (0\~1)  
    (1 \- (c.embedding \<=\> '')) AS semantic\_score,  
    \-- 2\. 시간 점수 (최신일수록 1에 가까움, 1년 지나면 약 0.37)  
    EXP(\-0.001 \* EXTRACT(DAY FROM NOW() \- e.event\_date)) AS time\_score,  
    \-- 3\. 최종 가중 합산 (의미 70%, 시간 30%)  
    ((1 \- (c.embedding \<=\> '')) \* 0.7) \+   
    (EXP(\-0.001 \* EXTRACT(DAY FROM NOW() \- e.event\_date)) \* 0.3) AS final\_score  
FROM chunks c  
JOIN documents d ON c.document\_id \= d.id  
JOIN events e ON d.event\_id \= e.id  
WHERE e.year IN (2024, 2025) \-- 메타데이터 필터링  
ORDER BY final\_score DESC  
LIMIT 5;

이 쿼리는 의미적으로 관련성이 높으면서도, 가능한 최신 행사의 정보를 우선적으로 노출한다.

### **4.3 파싱 및 인입 파이프라인 (Ingestion Pipeline)**

Upstage API와 Gemini Vision을 결합하여 문서를 "지식"으로 변환하는 과정이다.1

1. **파일 수집:** Google Drive API 또는 rclone을 통해 GCE의 /tmp 디렉토리로 파일을 동기화한다. 폴더 경로를 파싱하여 year, category, event\_name을 추출하고 events 테이블에 등록한다.  
2. **구조화 (Upstage):**  
   * model="document-parse"를 호출하여 HTML 및 좌표 정보를 받는다.  
   * **헤더 기반 분할:** HTML 내의 \<h1\>, \<h2\> 태그나 "안건", "보고" 등의 키워드를 정규식으로 탐지하여, 문서를 논리적 Chunk 단위로 쪼갠다. 이것이 Parent Chunk가 된다.  
3. **이미지/도표 강화 (Gemini Vision):**  
   * 문서 내의 \<img\> 태그(Upstage가 추출한 표나 차트 이미지)를 감지한다.  
   * 해당 이미지를 Gemini 1.5 Flash에 전송하고, 다음과 같은 프롬프트를 사용한다: *"이 이미지는 회의 자료의 일부이다. 표라면 Markdown으로 변환하고, 차트라면 그 경향성을 상세히 묘사하라."*  
   * Gemini가 생성한 텍스트 설명을 원본 HTML의 \<img\> 태그와 교체(Replace)한다. 이를 통해 시각 정보가 텍스트 벡터로 변환되어 검색 가능해진다.  
4. **임베딩 및 저장:**  
   * 강화된 텍스트를 Child Chunk 단위로 나누어 임베딩하고, Parent Chunk와 함께 pgvector에 저장한다.

### **4.4 멀티턴(Multi-turn) 대화 전략**

"꼬리를 무는 질문"을 처리하기 위해, 대화의 맥락을 유지하면서 검색 쿼리를 재구성하는 전략을 사용한다.20

1. **대화 기록 버퍼:** Redis 등을 사용하여 최근 N개의 대화 턴(User Query \+ AI Response)을 저장한다.  
2. **쿼리 재작성 (Query Rewriting):** 사용자의 새로운 질문이 들어오면, 바로 검색하지 않고 Gemini에게 대화 기록과 함께 보낸다.  
   * *상황:* (이전 대화) "간식행사 예산 얼마야?" \-\> (답변) "50만 원입니다." \-\> (새 질문) "누가 담당했어?"  
   * *재작성 요청:* "위 대화 맥락을 고려하여, '누가 담당했어?'라는 질문을 완전한 문장으로 다시 써줘."  
   * *결과:* "간식행사의 담당자는 누구인가?"  
3. **검색 및 답변:** 재작성된 명확한 쿼리로 벡터 검색을 수행한다. 이렇게 하면 "누가"라는 모호한 질문도 정확한 문맥 안에서 처리될 수 있다.

## ---

**5\. 구현 가이드: Claude Opus 프롬프트 설계 (Implementation)**

이 설계안을 바탕으로 사용자가 Claude Opus를 통해 코드를 생성할 수 있도록 최적화된 프롬프트를 제공한다.

### **5.1 마스터 프롬프트 (Master Prompt)**

# **Role Definition**

당신은 서울대학교 컴퓨터공학부 학생회 전용 RAG 시스템인 'Council-AI'의 백엔드 리드 개발자입니다.

우리의 기술 스택은 FastAPI(Async), PostgreSQL(pgvector), Upstage Document Parser, Gemini 1.5 Flash, Google Cloud Platform입니다.

# **Project Constraints & Context**

1. **도메인 특성:** 데이터의 핵심 단위는 '행사(Event)'이며, 문서는 '안건(Agenda Item)' 단위로 관리됩니다. '결과지(Result Report)'는 가장 높은 신뢰도를 가집니다.  
2. **청킹 전략:** Parent-Child Chunking을 사용합니다. Parent는 '안건' 전체 텍스트, Child는 벡터 검색용 문단입니다.  
3. **개인정보:** '참가자 명단' 등의 파일은 내용은 무시하고 메타데이터만 별도 테이블에 저장합니다.  
4. **검색 로직:** Hybrid Search(Vector \+ Time Decay)를 사용합니다. 최신 행사가 더 높은 점수를 받아야 합니다.

# **Task: Implementation Plan**

다음의 요구사항에 맞춰 Python 코드를 작성해 주세요. (SQLModel 및 AsyncPG 사용)

## **1\. Database Schema (models.py)**

* Event, Document, Chunk, Reference 테이블을 정의하세요.  
* Chunk 테이블에는 embedding 컬럼(vector 768차원)과 hnsw 인덱스를 포함하세요.  
* Event 테이블에는 event\_date가 필수입니다.

## **2\. Ingestion Service (ingest.py)**

* Upstage API를 호출하여 문서를 HTML로 파싱하는 비동기 함수 parse\_document를 작성하세요.  
* 파싱된 HTML에서 \<h1\>, \<h2\> 태그 또는 정규식(예: ^안건 \\d+)을 기준으로 Parent Chunk를 나누는 로직을 구현하세요.  
* \<img\> 태그 발견 시, (Placeholder 함수로) Gemini Vision API를 호출하여 텍스트로 치환하는 로직을 주석과 함께 포함하세요.

## **3\. Retrieval Service (retriever.py)**

* 사용자의 쿼리 벡터와 임계값 k를 입력받아 검색하는 함수를 작성하세요.  
* **SQL 쿼리 작성 시:** (1 \- (embedding \<=\> query))로 코사인 유사도를 구하고, EXP(-0.001 \* (CURRENT\_DATE \- event\_date))로 시간 감쇠 점수를 계산하여, 두 점수를 가중 합산(유사도 0.7 \+ 시간 0.3)하는 로직을 포함하세요.

## **4\. Chat Endpoint (main.py)**

* /chat 엔드포인트를 구현하세요.  
* 입력된 history를 바탕으로 Gemini를 사용해 사용자의 질문을 '완전한 문장(Contextualized Query)'으로 재작성(Rewrite)하는 단계를 먼저 수행하세요.  
* 재작성된 쿼리로 retriever를 호출하고, 결과를 바탕으로 답변을 생성하세요.

각 코드 블록에는 도메인 로직(왜 이렇게 짰는지)에 대한 주석을 충실히 달아주세요.

## ---

**6\. 결론 및 제언 (Conclusion)**

Council-AI는 단순한 검색 엔진이 아니다. 이 시스템은 서울대학교 컴퓨터공학부 학생회의 \*\*'업무 기억(Institutional Memory)'\*\*을 보존하고, 매년 반복되는 행사 준비의 시행착오를 획기적으로 줄여줄 자산이다.

본 설계서는 **'행사' 중심의 데이터 구조화**, **Parent-Child 청킹을 통한 문맥 보존**, **Upstage API를 활용한 정교한 구조 인식**, 그리고 **시간 감쇠를 적용한 최신성 우대 검색**을 통해 사용자가 정의한 '정확도, 구체성, 유용성' 지표를 달성하도록 설계되었다.

특히 1주일이라는 짧은 MVP 기간 동안, 모든 기능을 완벽히 구현하기보다는 **'데이터 파이프라인(Ingestion & Parsing)'의 안정성**과 **'기본 검색 품질(Retrieval Quality)'** 확보에 집중할 것을 권장한다. UI/UX는 Google Docs 사이드바라는 친숙한 환경을 활용하므로, 백엔드 로직의 견고함이 곧 사용자 경험(UX)으로 직결될 것이다. 제공된 프롬프트와 가이드를 통해, 사용자와 팀원은 이 복잡한 기술 스택을 효율적으로 통합하여 성공적인 MVP를 런칭할 수 있을 것이다.

---

**참고 문헌 및 근거 (Citations):**

* 1 학생회 인수인계서 및 조직 구조  
* 1 기술 스택 및 파이프라인 기획안  
* 1 행사 생애주기 및 문서 흐름  
* 1 안건지 문서 구조  
* 1 결과지 문서 구조 및 안건 분류  
* 2 Parent-Child 청킹 전략  
* 11 Upstage 파서 및 HTML 구조 활용  
* 9 pgvector HNSW 인덱싱  
* 16 시간 감쇠 스코어링 (Time Decay)  
* 20 멀티턴 대화 및 쿼리 재작성 전략  
* 1 개인정보 및 제한적 데이터 처리

#### **참고 자료**

1. 서울대학교 컴퓨터공학부 학생회장단 인수인계서 From. \[명월\] To. \[FLOW\].pdf  
2. The Beauty of Parent-Child Chunking. Graph RAG Was Too Slow for Production, So This Parent-Child RAG System was useful \- Reddit, 1월 30, 2026에 액세스, [https://www.reddit.com/r/Rag/comments/1mtcvs7/the\_beauty\_of\_parentchild\_chunking\_graph\_rag\_was/](https://www.reddit.com/r/Rag/comments/1mtcvs7/the_beauty_of_parentchild_chunking_graph_rag_was/)  
3. Chunking Strategies for AI and RAG Applications \- DataCamp, 1월 30, 2026에 액세스, [https://www.datacamp.com/blog/chunking-strategies](https://www.datacamp.com/blog/chunking-strategies)  
4. What is Metadata Filtering? Benefits, Best Practices & Tools \- lakeFS, 1월 30, 2026에 액세스, [https://lakefs.io/blog/metadata-filtering/](https://lakefs.io/blog/metadata-filtering/)  
5. Metadata-Based Filtering in RAG Systems | CodeSignal Learn, 1월 30, 2026에 액세스, [https://codesignal.com/learn/courses/scaling-up-rag-with-vector-databases/lessons/metadata-based-filtering-in-rag-systems](https://codesignal.com/learn/courses/scaling-up-rag-with-vector-databases/lessons/metadata-based-filtering-in-rag-systems)  
6. RAG Knowledge Base's “Family Meeting”: Why the “Parent-Child Mode” is Your AI's New Weapon \- Chwang, 1월 30, 2026에 액세스, [https://chwang12341.medium.com/rag-knowledge-bases-family-meeting-why-the-parent-child-mode-is-your-ai-s-new-weapon-22198b390197](https://chwang12341.medium.com/rag-knowledge-bases-family-meeting-why-the-parent-child-mode-is-your-ai-s-new-weapon-22198b390197)  
7. Chunking strategies for RAG applications \- Amazon Bedrock Recipes \- GitHub Pages, 1월 30, 2026에 액세스, [https://aws-samples.github.io/amazon-bedrock-samples/rag/open-source/chunking/rag\_chunking\_strategies\_langchain\_bedrock/](https://aws-samples.github.io/amazon-bedrock-samples/rag/open-source/chunking/rag_chunking_strategies_langchain_bedrock/)  
8. Parent-Child Chunking in LangChain for Advanced RAG | by Seahorse \- Medium, 1월 30, 2026에 액세스, [https://medium.com/@seahorse.technologies.sl/parent-child-chunking-in-langchain-for-advanced-rag-e7c37171995a](https://medium.com/@seahorse.technologies.sl/parent-child-chunking-in-langchain-for-advanced-rag-e7c37171995a)  
9. Faster similarity search performance with pgvector indexes | Google Cloud Blog, 1월 30, 2026에 액세스, [https://cloud.google.com/blog/products/databases/faster-similarity-search-performance-with-pgvector-indexes](https://cloud.google.com/blog/products/databases/faster-similarity-search-performance-with-pgvector-indexes)  
10. Speed up PostgreSQL® pgvector queries with indexes, 1월 30, 2026에 액세스, [https://aiven.io/developer/postgresql-pgvector-indexes](https://aiven.io/developer/postgresql-pgvector-indexes)  
11. AWS Marketplace: Document Parse \- Amazon.com, 1월 30, 2026에 액세스, [https://aws.amazon.com/marketplace/pp/prodview-lv5bnpdco7xoq](https://aws.amazon.com/marketplace/pp/prodview-lv5bnpdco7xoq)  
12. AI-powered table recognition just got smarter—here's how \- Upstage AI, 1월 30, 2026에 액세스, [https://www.upstage.ai/blog/en/ai-powered-table-recognition-just-got-smarter](https://www.upstage.ai/blog/en/ai-powered-table-recognition-just-got-smarter)  
13. Why table structure extraction fails: A deep dive into real-world challenges \- Upstage AI, 1월 30, 2026에 액세스, [https://www.upstage.ai/blog/en/why-table-structure-extraction-fails-a-deep-dive-into-real-world-challenges](https://www.upstage.ai/blog/en/why-table-structure-extraction-fails-a-deep-dive-into-real-world-challenges)  
14. Parse Documents into Structured Data | Upstage API, 1월 30, 2026에 액세스, [https://console.upstage.ai/docs/capabilities/digitize/api-quickstart](https://console.upstage.ai/docs/capabilities/digitize/api-quickstart)  
15. serithemage/updoc: CLI tool for Upstage Document Parse API \- GitHub, 1월 30, 2026에 액세스, [https://github.com/serithemage/updoc](https://github.com/serithemage/updoc)  
16. pgvector Hybrid Search: Benefits, Use Cases & Quick Tutorial, 1월 30, 2026에 액세스, [https://www.instaclustr.com/education/vector-database/pgvector-hybrid-search-benefits-use-cases-and-quick-tutorial/](https://www.instaclustr.com/education/vector-database/pgvector-hybrid-search-benefits-use-cases-and-quick-tutorial/)  
17. Updated timestamp sort decay algorithm \- Stack Overflow, 1월 30, 2026에 액세스, [https://stackoverflow.com/questions/20256396/updated-timestamp-sort-decay-algorithm](https://stackoverflow.com/questions/20256396/updated-timestamp-sort-decay-algorithm)  
18. Showing posts by their time-decayed score \- Software Engineering Stack Exchange, 1월 30, 2026에 액세스, [https://softwareengineering.stackexchange.com/questions/430352/showing-posts-by-their-time-decayed-score](https://softwareengineering.stackexchange.com/questions/430352/showing-posts-by-their-time-decayed-score)  
19. Exponential Decay | Milvus Documentation, 1월 30, 2026에 액세스, [https://milvus.io/docs/exponential-decay.md](https://milvus.io/docs/exponential-decay.md)  
20. Multi-turn Conversations with Agents: Building Context Across Dialogues, 1월 30, 2026에 액세스, [https://medium.com/@sainitesh/multi-turn-conversations-with-agents-building-context-across-dialogues-f0d9f14b8f64](https://medium.com/@sainitesh/multi-turn-conversations-with-agents-building-context-across-dialogues-f0d9f14b8f64)  
21. Simplifying RAG Context Windows — How to Stop Your Agent Forgetting | by Levi Stringer, 1월 30, 2026에 액세스, [https://medium.com/@levi\_stringer/simplifying-rag-context-windows-with-conversation-buffers-how-to-stop-your-agent-forgetting-df2149ad7403](https://medium.com/@levi_stringer/simplifying-rag-context-windows-with-conversation-buffers-how-to-stop-your-agent-forgetting-df2149ad7403)

[image1]: <data:image/png;base64,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>