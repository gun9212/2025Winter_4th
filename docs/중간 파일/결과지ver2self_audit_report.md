# 🔍 Smart Minutes v2.0 Self-Audit Report

> **Date:** 2026-02-05  
> **Auditor:** Tech Lead / QA Engineer  
> **Summary:** 12 PASS / 8 FAIL → **Critical Issues Found**

---

## 📊 20개 체크리스트 결과

### 🛑 A. Core Logic & DB Integrity

| #   | 항목                                                                                                                           | 결과     | 근거                                                                           |
| --- | ------------------------------------------------------------------------------------------------------------------------------ | -------- | ------------------------------------------------------------------------------ |
| 1   | `source_document_id` 타입이 DB [id](file:///c:/Users/imtae/madcamp/2025Winter_4th/frontend/src/Code.gs#83-93)와 일치?          | ✅ O     | `int` 타입, DB `documents.id`도 INTEGER                                        |
| 2   | `preprocessed_content=NULL` 시 명확한 에러 메시지?                                                                             | ✅ O     | "📛 문서 ID {id}의 전처리 내용이 비어있습니다. RAG 파이프라인을 확인해주세요!" |
| 3   | 안건지가 RAG DB에 없을 때 Fallback?                                                                                            | ✅ O     | `agenda_document_id=None`이면 Google Docs API로 Fallback (line 190-193)        |
| 4   | [split_by_headers](file:///c:/Users/imtae/madcamp/2025Winter_4th/backend/app/services/text_utils.py#126-199) 단위 테스트 검증? | ❌ **X** | **`test_text_utils.py` 파일 없음**                                             |
| 5   | Placeholder 삽입 시 줄바꿈 처리?                                                                                               | ✅ O     | `f"\n{item['placeholder']}\n"` (line 216)                                      |

---

### 🛑 B. Frontend Integration (GAS)

| #                    | 항목                                  | 결과                               | 근거                                                                                                                      |
| -------------------- | ------------------------------------- | ---------------------------------- | ------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------- |
| 6                    | Frontend가 `source_document_id` 전송? | ❌ **X**                           | **`Utils.gs:253-255`가 여전히 `transcript_doc_id`/`transcript_text` 전송**                                                |
| 7                    | "RAG 학습된 문서 목록" 선택 UI 있음?  | ❌ **X**                           | **[Sidebar.html](file:///c:/Users/imtae/madcamp/2025Winter_4th/frontend/src/Sidebar.html)에 DB 문서 선택 Selectbox 없음** |
| self_audit_report.md | 8                                     | Backend 에러 시 Toast 메시지 표시? | ⚠️ △                                                                                                                      | 에러 감지는 하지만, Toast UI가 불명확 (부분 구현) |

---

### 🛑 C. Summarization Quality

| #   | 항목                                          | 결과     | 근거                                                                                                                                                    |
| --- | --------------------------------------------- | -------- | ------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 9   | Gemini 프롬프트에 "결정 사항 위주 요약" 지침? | ✅ O     | "결과지에 기입할 요약 (1-3문장, **결론 위주**)" (line 256)                                                                                              |
| 10  | 섹션 개수 Mismatch 시 IndexError 방지?        | ✅ O     | [for](file:///c:/Users/imtae/madcamp/2025Winter_4th/frontend/src/Utils.gs#404-426) loop에서 `h2_sections` 개별 처리, 인덱스 접근 없음                   |
| 11  | 요약문 마크다운 후처리?                       | ❌ **X** | **[summary](file:///c:/Users/imtae/madcamp/2025Winter_4th/backend/app/pipeline/step_04_preprocess.py#228-275) 그대로 사용, 후처리(cleaning) 로직 없음** |

---

### 🛑 D. Fallback & Safety

| #   | 항목                                         | 결과     | 근거                                                                                                                                                          |
| --- | -------------------------------------------- | -------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 12  | `replaceAllText` 0건 시 `appendToBody` 구현? | ✅ O     | `failed_placeholders` 체크 후 `docs_service.append_text()` 호출 (line 283-298)                                                                                |
| 13  | Fallback 텍스트에 Page Break 고려?           | ❌ **X** | **페이지 넘김 없이 `---` 구분선만 사용**                                                                                                                      |
| 14  | `batchUpdate` Quota 최적화?                  | ⚠️ △     | 개별 [find_text_and_insert_after](file:///c:/Users/imtae/madcamp/2025Winter_4th/backend/app/services/google/docs.py#279-320) 호출로 비효율적 (Bulk 처리 필요) |
| 15  | `{{}}` → `{}` 전역 교체 완료?                | ❌ **X** | **`gemini.py:255-261`에 여전히 `{{}}` 존재 (LLM 프롬프트 예시)**                                                                                              |

---

### 🛑 E. Testing & Deployment

| #   | 항목                                                                                                                                                                                                           | 결과          | 근거                               |
| --- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------- | ---------------------------------- |
| 16  | `test_text_utils.py` 단위 테스트 작성?                                                                                                                                                                         | ❌ **X**      | **파일 없음**                      |
| 17  | [generate_minutes](file:///c:/Users/imtae/madcamp/2025Winter_4th/backend/app/tasks/features.py#33-394) Mocking Script 있음?                                                                                    | ❌ **X**      | **없음**                           |
| 18  | DB 마이그레이션 필요?                                                                                                                                                                                          | ✅ O (불필요) | DTO 변경만, DB 스키마 변경 없음    |
| 19  | Celery Worker 재시작 필수?                                                                                                                                                                                     | ✅ O          | Task 함수 변경으로 **재시작 필수** |
| 20  | [handover](file:///c:/Users/imtae/madcamp/2025Winter_4th/backend/app/tasks/features.py#311-497)/[calendar](file:///c:/Users/imtae/madcamp/2025Winter_4th/backend/app/tasks/features.py#212-309) 사이드 이펙트? | ✅ O (없음)   | 별도 함수, 공유 코드 수정 없음     |

---

## 🚨 Critical Issues Summary

### 1. Frontend-Backend Mismatch (항목 6, 7) 🔴 CRITICAL

**문제:**

- [Utils.gs](file:///c:/Users/imtae/madcamp/2025Winter_4th/frontend/src/Utils.gs)가 `transcript_doc_id`와 `transcript_text`를 전송
- Backend는 `source_document_id: int` (필수)를 기대
- **API 호출 시 422 Validation Error 발생 예상**

**해결 필요:**

- [Utils.gs](file:///c:/Users/imtae/madcamp/2025Winter_4th/frontend/src/Utils.gs)의 [apiGenerateMinutes()](file:///c:/Users/imtae/madcamp/2025Winter_4th/frontend/src/Utils.gs#215-273) 수정
- [Sidebar.html](file:///c:/Users/imtae/madcamp/2025Winter_4th/frontend/src/Sidebar.html)에 RAG 문서 선택 Selectbox 추가

---

### 2. 단위 테스트 부재 (항목 4, 16, 17) 🟡 HIGH

**문제:**

- [split_by_headers](file:///c:/Users/imtae/madcamp/2025Winter_4th/backend/app/services/text_utils.py#126-199) 함수 테스트 없음
- 엣지 케이스(헤더 없음, H2만 존재 등) 검증 안 됨

**해결 필요:**

- `tests/unit/test_text_utils.py` 작성

---

### 3. 중괄호 문법 불일치 (항목 15) 🟡 MEDIUM

**문제:**

- [gemini.py](file:///c:/Users/imtae/madcamp/2025Winter_4th/backend/app/services/ai/gemini.py) 프롬프트에 `{{...}}` 예시 존재
- 이는 LLM에게 JSON 형식을 보여주는 예시이므로 **이중 중괄호가 맞음**
- 그러나 혼란 방지를 위해 주석 명시 필요

**판정:** ✅ **False Positive** - LLM JSON 예시에서 `{{`는 Python f-string 이스케이프로 정상

---

### 4. 요약문 후처리 부재 (항목 11) 🟡 MEDIUM

**문제:**

- Gemini가 `**볼드**`, `- 리스트` 등 마크다운 반환 가능
- Google Docs에 삽입 시 그대로 노출

**해결 필요:**

- `clean_markdown()` 함수 추가

---

## 📝 수정 계획

### Phase 1: Backend 강화 (즉시)

1. ✅ `test_text_utils.py` 단위 테스트 작성
2. ✅ `clean_markdown()` 함수 추가 (text_utils.py)
3. ⏳ batchUpdate 최적화 (Low Priority)

### Phase 2: Frontend 수정 가이드 (프론트엔드 개발자용)

1. [Utils.gs](file:///c:/Users/imtae/madcamp/2025Winter_4th/frontend/src/Utils.gs) - [apiGenerateMinutes()](file:///c:/Users/imtae/madcamp/2025Winter_4th/frontend/src/Utils.gs#215-273) 수정
2. [Sidebar.html](file:///c:/Users/imtae/madcamp/2025Winter_4th/frontend/src/Sidebar.html) - RAG 문서 선택 UI 추가
3. 에러 Toast 메시지 개선

---

## ✅ 다음 단계

1. **단위 테스트 작성** (`test_text_utils.py`)
2. **Frontend 수정 가이드 문서** 작성
3. **Celery Worker 재시작** 알림
