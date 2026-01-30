# Council-AI: 학생회 업무 자동화 및 지식 관리 솔루션

> "복잡한 행정은 AI에게, 학생회는 학우에게 집중하도록."

## 프로젝트 개요

- **프로젝트명:** Council-AI (학생회 AI 비서)
- **목표:** Google Workspace 기반의 문서 데이터 파이프라인 구축 및 RAG를 통한 지식 자산화, 업무 자동화
- **핵심 가치:**
  - **자산화:** 휘발되는 회의록과 자료를 '검색 가능한 DB'로 영구 저장
  - **자동화:** 회의 결과 정리부터 캘린더 등록까지의 수작업 제거
  - **연결성:** 별도 앱 설치 없이 기존 Google Docs 환경(Sidebar)에서 즉시 실행

## 기술 스택 (GCP Native)

| 구분 | 기술 | 설명 |
|------|------|------|
| Frontend | Google Apps Script (GAS) | 구글 닥스 사이드바 내 동작, HTML/CSS/JS UI |
| Backend | FastAPI (Python) | 비동기 처리 최적화, AI 라이브러리 호환성 |
| Infrastructure | GCP Compute Engine | e2-medium 인스턴스, Docker & Docker Compose |
| Parsing | Upstage Doc Parser API | 표(Table) 구조 인식 및 HTML 변환 |
| AI Models | Gemini 1.5 Flash | 1M Token Context, Vision 캡셔닝 |
| Storage | Google Cloud Storage (GCS) | 이미지 원본 저장소 |
| Database | PostgreSQL + pgvector | 정형/비정형 데이터 통합 관리, Docker 컨테이너 |
| Task Queue | Celery + Redis | 비동기 작업 처리 |
| Auth | Google Service Account | ADC(Application Default Credentials) 방식 |

## 핵심 기능

### Feature 1. 회의 자동화 (Smart Minutes)
- **Input:** 안건지(Google Docs ID) + 녹음본/속기록 텍스트
- **Process:**
  1. Docs API로 안건지 템플릿 로드
  2. LLM이 속기록 분석 → `결정 사항`, `액션 아이템` 추출
  3. 템플릿 Placeholder 치환 (`batchUpdate`)
- **Output:** 완성된 결과지 Docs 생성

### Feature 2. 지능형 지식 DB (Hybrid RAG) [Core]
- **Pipeline:** Ingestion → Parsing → Enrichment → Indexing
- **Search:** 질문 → 임베딩 → Cosine Similarity → LLM 답변
- **Biz Logic:** '간식', '회식' 키워드 시 제휴 업체 정보 함께 검색

### Feature 3. 스마트 캘린더 (Shared Calendar)
- 공유 캘린더 구독 방식
- 결과지에서 `[날짜]`, `[담당자]`, `[할일]` 추출 → 이벤트 생성

## 데이터 파이프라인

### 1. Ingestion (수집)
- **Source:** Google Drive (사용자 지정 폴더)
- **Method:**
  - 초기 구축: `rclone` 대량 동기화
  - 실시간: Google Drive API + ADC 인증 (`google.auth.default()`)
- **Conversion:** Docs/Sheets → `.docx`, `.xlsx` 자동 변환
- **Destination:** GCE `/tmp/ingestion`

### 2. Parsing (구조화)
- **Tool:** Upstage Document Parser API
- **Process:** 파일 → HTML/Markdown 변환 (표 구조 보존)
- **Extraction:** 이미지 별도 추출 → 로컬 임시 저장

### 3. Enrichment (AI 분석)
- **Vision:** 이미지 → GCS 버킷 업로드 → `gs://council-data/images/...`
- **Captioning:** Gemini 1.5 Flash로 이미지 설명 생성
  - Prompt: "이 이미지가 표나 조직도라면 마크다운으로 구조를 텍스트화하고, 일반 사진이라면 상황을 상세 묘사해 줘."
- **Merge:** `<img>` 태그 → 설명 텍스트로 치환

### 4. Indexing (저장)
- **Chunking:** LangChain 의미 단위 분할
- **Embedding:** Gemini Embedding Model
- **DB Insert:** PostgreSQL (pgvector) + 메타데이터

### 5. Cleanup (정리)
- 작업 완료 즉시 `/tmp` 내 파일 영구 삭제

---

## 개발 규칙

### 코드 작성 규칙
- **절대 모킹하지 않기**: 실제 동작하는 코드만 작성
- **타입 안전성**: TypeScript 엄격 모드 준수
- **테스트 우선**: 테스트 커버리지 90% 이상 유지
- **컴포넌트 네이밍**: PascalCase, 기능을 명확히 나타내는 이름 사용
- **React import**: 타입 사용 시 named import (`import { type ReactNode, type FC } from 'react';`)

### 패키지 버전 호환성
- React 19.1.1 고정 (resolutions 설정됨)
- @wishket 패키지들과의 호환성 유지
- 새 패키지 추가 시 기존 의존성과 충돌 확인

### 파일 구조 규칙
- `index.ts`로 export 모듈화
- `.unit.spec.tsx` 확장자로 단위 테스트 작성
- `.types.ts`, `.constants.ts`, `.utils.ts` 분리

### 스크립트 명령어
```bash
yarn dev          # 개발 서버 (Turbopack)
yarn build        # 프로덕션 빌드
yarn lint         # ESLint 검사
yarn test:unit    # Jest 단위 테스트
yarn test:e2e     # Cypress E2E 테스트
```

---

## 개발 워크플로우 (증강 코딩 + TDD)

### 켄트 벡의 증강 코딩 원칙
- **증강 코딩 vs 바이브 코딩**: 코드 품질, 테스트, 단순성을 중시하되 AI와 협업
- **중간 결과 관찰**: AI가 반복 동작, 요청하지 않은 기능 구현, 테스트 삭제 등의 신호를 보이면 즉시 개입
- **설계 주도권 유지**: AI가 너무 앞서가지 않도록 개발자가 설계 방향 제시

### TDD 워크플로우 (Red → Green → Refactor)

#### 1. Red Phase - 실패하는 테스트 먼저 작성
```typescript
// *.unit.spec.tsx 파일 생성
describe('새 기능', () => {
  it('원하는 동작을 명확히 기술', () => {
    // 아직 구현되지 않은 기능 테스트
    expect(실제결과).toBe(기대결과);
  });
});
```

#### 2. Green Phase - 최소한의 구현
- 타입 정의 (*.types.ts)
- 실제 동작 코드 (*.tsx, *.ts)
- 오버엔지니어링 금지

#### 3. Refactor Phase - 테스트 유지하며 개선
- 중복 제거
- 가독성 개선
- 성능 최적화
- 테스트는 계속 통과해야 함

### 실제 개발 순서
1. 테스트 먼저 작성 (*.unit.spec.tsx) - 기능 요구사항을 테스트로 표현
2. 실패하는 테스트 확인 (Red)
3. 타입 정의 (*.types.ts) - 테스트에 필요한 타입만 정의
4. 최소 구현 (Green)
5. 리팩토링 (Refactor)

---

## 특별 주의사항

### 절대 하지 말 것
- Mock 데이터나 가짜 구현 사용
- 타입 `any` 사용
- 직접적인 DOM 조작
- `console.log` 프로덕션 코드에 남기기
- 스스로 깃허브 레포에 push 하지 말고, 사용자에게 물어볼 것.
- 사용자가 깃허브 액션에 대해 물어봐도, 해결법에 대해서만 알려주고 스스로 실행하지 말 것.

### 권장사항
- 실제 API 호출하는 코드 작성
- 재사용 가능한 컴포넌트 설계
- 접근성(a11y) 고려
- 성능 최적화 적용

### 문제 해결 우선순위
1. 실제 동작하는 해결책 찾기
2. 기존 코드 패턴 분석 후 일관성 유지
3. 타입 안전성 보장
4. 테스트 가능한 구조로 설계

---

## 디렉토리 구조

```
week4/
├── CLAUDE.md
├── backend/           # FastAPI 백엔드
│   ├── app/
│   │   ├── api/       # API 엔드포인트
│   │   ├── core/      # 설정, 보안
│   │   ├── services/  # 비즈니스 로직
│   │   ├── models/    # DB 모델
│   │   └── schemas/   # Pydantic 스키마
│   ├── tests/
│   └── Dockerfile
├── frontend/          # Google Apps Script
│   ├── src/
│   └── appsscript.json
├── docker-compose.yml
└── .env.example
```
