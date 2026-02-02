# Council-AI 통신 흐름 다이어그램

## 1. Smart Minutes (결과지 자동 생성)

### 전체 흐름

```mermaid
sequenceDiagram
    autonumber
    participant FE as Frontend<br/>(Apps Script)
    participant API as FastAPI
    participant Celery as Celery Worker
    participant Redis as Redis Queue
    participant Docs as Google Docs API
    participant AI as Gemini API

    FE->>API: POST /minutes/generate
    Note over FE,API: agenda_doc_id, transcript_doc_id
    
    API->>Redis: 📤 Task Enqueue
    Redis-->>API: task_id
    API-->>FE: 202 Accepted {task_id, status: PENDING}
    
    Note over FE: Polling 시작 (2초 간격)
    
    Celery->>Redis: 📥 Task Dequeue
    
    rect rgb(255, 230, 230)
        Note over Celery,Docs: ⚠️ ERROR ZONE 1: API 호출
        Celery->>Docs: GET transcript text
        Docs-->>Celery: transcript content
    end
    
    Celery->>Celery: split_by_headers()
    Note over Celery: 섹션 분할
    
    loop 각 섹션별
        rect rgb(255, 230, 230)
            Note over Celery,AI: ⚠️ ERROR ZONE 2: AI 요청
            Celery->>AI: summarize_agenda_section()
            AI-->>Celery: 요약 결과
        end
    end
    
    rect rgb(255, 230, 230)
        Note over Celery,Docs: ⚠️ ERROR ZONE 3: 문서 복사
        Celery->>Docs: copy_document(agenda_doc_id)
        Docs-->>Celery: new_doc_id
    end
    
    Celery->>Docs: replace_text() x N
    Note over Celery,Docs: Placeholder 치환
    
    Celery->>Redis: ✅ Task Complete
    
    FE->>API: GET /minutes/{task_id}/status
    API->>Redis: Get Task Result
    Redis-->>API: {status: SUCCESS, result_doc_id}
    API-->>FE: 200 OK {result_doc_id, doc_link}
```

### 에러 발생 가능 포인트

| Zone | 상황 | 원인 | 대응 |
|------|------|------|------|
| 1 | Google Docs 접근 실패 | 문서 공유 안됨, 잘못된 ID | 400 Bad Request + 상세 메시지 |
| 2 | Gemini 요청 실패 | Rate Limit, 토큰 초과 | Retry 3회 후 Partial 결과 반환 |
| 3 | 문서 복사 실패 | Drive 권한 없음 | 500 Internal Error |

---

## 2. Calendar Sync (Human-in-the-Loop)

### 전체 흐름

```mermaid
sequenceDiagram
    autonumber
    participant User as 사용자
    participant FE as Frontend<br/>(Apps Script)
    participant API as FastAPI
    participant Docs as Google Docs API
    participant AI as Gemini API
    participant Cal as Google Calendar API

    User->>FE: "Todo 추출" 버튼 클릭
    FE->>API: POST /calendar/extract-todos
    Note over FE,API: {result_doc_id}
    
    rect rgb(255, 230, 230)
        Note over API,Docs: ⚠️ ERROR ZONE 1
        API->>Docs: GET document text
        Docs-->>API: document content
    end
    
    rect rgb(255, 230, 230)
        Note over API,AI: ⚠️ ERROR ZONE 2
        API->>AI: extract_todos_from_document()
        AI-->>API: todos JSON
    end
    
    API-->>FE: 200 OK {todos: [...]}
    FE-->>User: Todo 목록 표시
    
    Note over User: 🧑 Human Review<br/>수정/삭제/날짜 확정
    
    User->>FE: "캘린더 등록" 클릭
    FE->>API: POST /calendar/events/create
    Note over FE,API: {summary, dt_start, ...}
    
    rect rgb(255, 230, 230)
        Note over API,Cal: ⚠️ ERROR ZONE 3
        API->>Cal: create_event()
        Cal-->>API: event_id
    end
    
    API-->>FE: 201 Created {event_id, link}
    FE-->>User: ✅ 등록 완료 표시
```

### Human-in-the-Loop 설계 이유

```mermaid
flowchart TD
    A[AI 추출 Todo] --> B{날짜 파싱 성공?}
    B -->|Yes| C[parsed_date 제공]
    B -->|No| D[parsed_date: null]
    
    C --> E[사용자 확인]
    D --> E
    
    E --> F{사용자 수정?}
    F -->|Yes| G[수정된 값 사용]
    F -->|No| H[원본 값 사용]
    
    G --> I[캘린더 등록]
    H --> I
    
    style B fill:#ffcccc
    style E fill:#ccffcc
```

**왜 Human-in-the-Loop인가?**
1. 날짜 파싱 불확실성: "다음 주", "빠른 시일 내" 등 모호한 표현
2. 우선순위 판단 필요: 모든 Todo가 캘린더에 등록될 필요는 없음
3. 담당자 확인: AI가 추출한 담당자가 실제 이메일과 매칭되는지 확인 필요

### 에러 발생 가능 포인트

| Zone | 상황 | 원인 | 대응 |
|------|------|------|------|
| 1 | 문서 텍스트 추출 실패 | 문서 접근 권한 없음 | 403 Forbidden |
| 2 | Todo 추출 실패 | AI 응답 파싱 오류 | 빈 배열 반환 |
| 3 | 이벤트 생성 실패 | 캘린더 쓰기 권한 없음 | 403 Forbidden |

---

## 3. Handover (인수인계서 생성)

### 전체 흐름

```mermaid
sequenceDiagram
    autonumber
    participant FE as Frontend<br/>(Apps Script)
    participant API as FastAPI
    participant Celery as Celery Worker
    participant Redis as Redis Queue
    participant DB as PostgreSQL
    participant AI as Gemini API
    participant Docs as Google Docs API

    FE->>API: POST /handover/generate
    Note over FE,API: {target_year, department, ...}
    
    API->>Redis: 📤 Task Enqueue
    Redis-->>API: task_id
    API-->>FE: 202 Accepted {task_id}
    
    Note over FE: Polling 시작 (5초 간격)
    
    Celery->>Redis: 📥 Task Dequeue
    
    rect rgb(255, 230, 230)
        Note over Celery,DB: ⚠️ ERROR ZONE 1: DB 쿼리
        Celery->>DB: SELECT events WHERE year=?
        DB-->>Celery: events[]
        Celery->>DB: SELECT documents by event_ids
        DB-->>Celery: documents[]
    end
    
    Celery->>Celery: 데이터 구조화
    Note over Celery: event별 document 매핑
    
    rect rgb(255, 230, 230)
        Note over Celery,AI: ⚠️ ERROR ZONE 2: AI 생성
        Celery->>AI: generate_handover_content()
        Note over AI: 통계, 인사이트, 개선제안 생성
        AI-->>Celery: handover content
    end
    
    rect rgb(255, 230, 230)
        Note over Celery,Docs: ⚠️ ERROR ZONE 3: 문서 생성
        Celery->>Docs: create_document()
        Docs-->>Celery: new_doc_id
        Celery->>Docs: insert_text(content)
        Docs-->>Celery: OK
    end
    
    Celery->>Redis: ✅ Task Complete
    
    FE->>API: GET /handover/{task_id}/status
    API->>Redis: Get Task Result
    Redis-->>API: {status: SUCCESS}
    API-->>FE: 200 OK {output_doc_id, doc_link}
```

### 데이터 흐름

```mermaid
flowchart LR
    subgraph DB["PostgreSQL"]
        E[Event 테이블]
        D[Document 테이블]
    end
    
    subgraph Process["Celery Task"]
        Q[연도별 쿼리]
        M[데이터 매핑]
        G[AI 생성]
    end
    
    subgraph Output["결과물"]
        H[인수인계서]
    end
    
    E --> Q
    D --> Q
    Q --> M
    M --> G
    G --> H
```

### 에러 발생 가능 포인트

| Zone | 상황 | 원인 | 대응 |
|------|------|------|------|
| 1 | DB 쿼리 실패 | 연결 끊김, 타임아웃 | Retry + 알림 |
| 2 | AI 생성 실패 | 토큰 초과 (많은 데이터) | 데이터 청킹 |
| 3 | 문서 생성 실패 | Drive 용량 부족 | 사용자에게 알림 |

---

## 4. 공통 에러 처리 패턴

### Celery Task 에러 핸들링

```mermaid
flowchart TD
    A[Task 실행] --> B{성공?}
    B -->|Yes| C[✅ SUCCESS 상태]
    B -->|No| D{Retry 횟수?}
    D -->|< 3| E[🔄 Retry]
    E --> A
    D -->|>= 3| F[❌ FAILURE 상태]
    
    C --> G[결과 저장]
    F --> H[에러 메시지 저장]
    
    G --> I[Frontend Polling]
    H --> I
```

### 상태 코드 매핑

| Celery State | HTTP Status | 의미 |
|--------------|-------------|------|
| PENDING | 202 | 대기 중 |
| STARTED | 202 | 처리 중 |
| SUCCESS | 200 | 완료 |
| FAILURE | 500 | 실패 |
| REVOKED | 410 | 취소됨 |

---

## 5. 전체 시스템 상태 다이어그램

```mermaid
stateDiagram-v2
    [*] --> PENDING: Task 생성
    PENDING --> STARTED: Worker 시작
    STARTED --> SUCCESS: 정상 완료
    STARTED --> RETRY: 일시 오류
    RETRY --> STARTED: 재시도
    RETRY --> FAILURE: 최대 재시도 초과
    STARTED --> FAILURE: 치명적 오류
    SUCCESS --> [*]
    FAILURE --> [*]
```

---

## 6. 핵심 리스크 포인트 정리

```mermaid
mindmap
    root((에러 포인트))
        Google API
            인증 만료
            Rate Limit
            권한 부족
            문서 삭제됨
        Gemini API
            토큰 초과
            응답 파싱 실패
            Rate Limit
        Database
            연결 타임아웃
            데이터 없음
        Network
            외부 서비스 장애
            타임아웃
```

### 각 리스크별 대응 전략

| 리스크 | 탐지 | 대응 |
|--------|------|------|
| Google API 인증 만료 | 401 응답 | 토큰 자동 갱신 |
| Rate Limit | 429 응답 | 지수 백오프 재시도 |
| Gemini 토큰 초과 | 400 응답 | 입력 청킹 |
| DB 타임아웃 | ConnectionError | 연결 풀 재설정 |

---

*Last Updated: 2025-02-02*
