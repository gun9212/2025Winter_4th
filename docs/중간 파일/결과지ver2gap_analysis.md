# 🔍 Gap Analysis Note: Smart Minutes v2.0 Implementation

> **Date:** 2026-02-05  
> **Status:** Pre-Implementation Review

---

## 1. Frontend UX: 문서 목록 검색/정렬

### 문제점
- RAG 학습된 문서가 수백 개일 경우 단순 `<select>` 박스는 사용 불편

### 해결책 (구현에 반영)
```javascript
// 문서 목록 정렬: 최신순 (updated_at 기준)
documents.sort((a, b) => new Date(b.updated_at) - new Date(a.updated_at));

// 문서 개수 제한: 최근 50개만 표시
const recentDocs = documents.slice(0, 50);

// 옵션 텍스트에 날짜 명시하여 식별력 강화
// 예: "📝 제12차 운영위원회 속기록 (02/05)"
```

### 추가 개선 (v2.1)
- 추후 검색 기능 추가 고려 (input + filter)

---

## 2. Error Handling: 서버 연결 실패

### 문제점
- `apiGetRagDocuments` 호출 실패 시 사용자에게 명확한 메시지 필요

### 해결책 (구현에 반영)
```javascript
.withFailureHandler(function(error) {
  select.disabled = false;
  select.innerHTML = '<option value="">⚠️ 서버 연결 실패</option>';
  info.textContent = '서버가 응답하지 않습니다. 잠시 후 다시 시도해주세요.';
  console.error('[loadRagDocuments] Server error:', error);
})
```

### Error 유형별 처리
| HTTP Status | 메시지 |
|-------------|--------|
| 0 (Timeout) | "서버 연결 실패" |
| 401/403 | "인증 오류 - API Key 확인 필요" |
| 500+ | "서버 내부 오류" |
| 성공 but 빈 목록 | "RAG 학습된 문서가 없습니다" |

---

## 3. Type Safety: source_document_id

### 문제점
- GAS(JavaScript)에서 `<select>.value`는 항상 **문자열**("123")
- Backend `source_document_id: int`는 Integer 필요

### Pydantic 동작 분석
```python
source_document_id: int = Field(...)
# Pydantic v2는 문자열 "123"을 자동으로 int 123으로 변환 (coercion)
```

### 결론
- **Backend에서 자동 변환 처리됨** (Pydantic coercion)
- 그러나 **명시적 변환이 안전**하므로 GAS에서 `parseInt()` 적용

```javascript
// Utils.gs
source_document_id: parseInt(params.sourceDocumentId, 10)
```

### 추가 방어 로직
```javascript
// NaN 방지
if (isNaN(sourceDocumentId) || sourceDocumentId <= 0) {
  return { success: false, error: '유효하지 않은 문서 ID입니다.' };
}
```

---

## 4. 기타 발견 사항

### 4.1 Sidebar.html 기존 로직 유지
- 기존 Picker 기반 `transcript-doc-id`는 **주석 처리**하고 유지 (Fallback)
- 새로운 Selectbox `source-document-id` 추가

### 4.2 Backend 호환성
- deprecated 필드 (`transcript_doc_id`, `transcript_text`)는 유지
- `source_document_id` 없이 요청 시 Pydantic Validation Error (422)

### 4.3 문서 필터링
- COMPLETED 상태만 조회하여 RAG 학습 완료된 문서만 표시
- `doc_type` 필터는 optional (속기록만 표시 가능)

---

## ✅ 구현 체크리스트

- [x] 문서 목록 최신순 정렬
- [x] 문서 표시에 날짜 포함
- [x] 최근 50개 제한 (UX)
- [x] 서버 연결 실패 메시지
- [x] parseInt로 명시적 타입 변환
- [x] NaN 방어 로직
