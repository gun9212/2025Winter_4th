# 🔧 Frontend Integration Guide: Smart Minutes v2.0

> **대상:** GAS (Google Apps Script) 프론트엔드 개발자  
> **작성일:** 2026-02-05  
> **상태:** CRITICAL - 백엔드 변경에 맞춰 수정 필수

---

## ⚠️ 현재 문제점

**Backend v2.0 변경 사항:**
- `source_document_id: int` (필수 필드) 추가
- `transcript_doc_id`/`transcript_text` (deprecated)

**Frontend 현재 상태:**
- [Utils.gs](file:///c:/Users/imtae/madcamp/2025Winter_4th/frontend/src/Utils.gs)가 여전히 `transcript_doc_id`/`transcript_text` 전송
- **API 호출 시 422 Validation Error 발생 예상**

---

## 📋 수정 체크리스트

- [ ] [Utils.gs](file:///c:/Users/imtae/madcamp/2025Winter_4th/frontend/src/Utils.gs) - [apiGenerateMinutes()](file:///c:/Users/imtae/madcamp/2025Winter_4th/frontend/src/Utils.gs#215-273) 함수 수정
- [ ] [Sidebar.html](file:///c:/Users/imtae/madcamp/2025Winter_4th/frontend/src/Sidebar.html) - RAG 문서 선택 UI 추가
- [ ] [Sidebar.html](file:///c:/Users/imtae/madcamp/2025Winter_4th/frontend/src/Sidebar.html) - 에러 Toast 메시지 개선

---

## 1. Utils.gs 수정

### 1.1 [apiGenerateMinutes()](file:///c:/Users/imtae/madcamp/2025Winter_4th/frontend/src/Utils.gs#215-273) 함수 수정

**파일:** [frontend/src/Utils.gs](file:///c:/Users/imtae/madcamp/2025Winter_4th/frontend/src/Utils.gs)  
**위치:** Line 225-272

#### 변경 전 (현재):

```javascript
function apiGenerateMinutes(params) {
  // transcript 소스 검증: doc_id나 text 중 하나는 필수
  const transcriptDocId = params.transcriptDocId && params.transcriptDocId.trim() !== '' 
    ? params.transcriptDocId.trim() 
    : null;
  const transcriptText = params.transcriptText && params.transcriptText.trim() !== ''
    ? params.transcriptText.trim()
    : null;
  
  if (!transcriptDocId && !transcriptText) {
    return {
      success: false,
      error: '속기록이 필요합니다...',
      statusCode: 0
    };
  }
  
  const payload = {
    agenda_doc_id: params.agendaDocId,
    transcript_doc_id: transcriptDocId,
    transcript_text: transcriptText,
    // ...
  };
  
  return callAPI('/minutes/generate', 'POST', payload);
}
```

#### 변경 후 (v2.0):

```javascript
/**
 * 결과지 생성 요청 (v2.0)
 * @param {Object} params - 생성 파라미터
 * @returns {Object} task_id 포함 응답
 * 
 * v2.0 변경사항:
 * - source_document_id (필수): RAG 파이프라인으로 처리된 DB 문서 ID
 * - transcript_doc_id, transcript_text: DEPRECATED
 */
function apiGenerateMinutes(params) {
  // v2.0: source_document_id 필수 검증
  if (!params.sourceDocumentId) {
    return {
      success: false,
      error: '속기록 문서를 선택해주세요. RAG 자료학습이 완료된 문서만 선택 가능합니다.',
      statusCode: 0
    };
  }
  
  // meeting_date가 Date 객체면 YYYY-MM-DD로 변환
  let meetingDate = params.meetingDate;
  if (meetingDate instanceof Date) {
    meetingDate = formatDate(meetingDate, 'YYYY-MM-DD');
  }
  
  // 현재 사용자 이메일 가져오기
  const userEmail = Session.getActiveUser().getEmail();
  
  const payload = {
    agenda_doc_id: params.agendaDocId,
    source_document_id: params.sourceDocumentId,  // v2.0 필수
    agenda_document_id: params.agendaDocumentId || null,  // v2.0 선택
    template_doc_id: params.templateDocId && params.templateDocId.trim() !== '' 
      ? params.templateDocId.trim() 
      : null,
    meeting_name: params.meetingName,
    meeting_date: meetingDate,
    output_folder_id: params.outputFolderId && params.outputFolderId.trim() !== ''
      ? params.outputFolderId.trim()
      : null,
    output_doc_id: params.outputDocId && params.outputDocId.trim() !== ''
      ? params.outputDocId.trim()
      : null,
    user_level: params.userLevel || 2,
    user_email: userEmail || null
  };
  
  return callAPI('/minutes/generate', 'POST', payload);
}
```

### 1.2 RAG 문서 목록 조회 API 추가

```javascript
/**
 * RAG 학습 완료된 문서 목록 조회
 * @param {number} skip - 페이지네이션 오프셋
 * @param {number} limit - 페이지 크기
 * @returns {Object} 문서 목록 { success, data: { documents: [...] } }
 */
function apiGetRagDocuments(skip, limit) {
  // COMPLETED 상태의 문서만 조회
  const endpoint = '/rag/documents?skip=' + (skip || 0) + '&limit=' + (limit || 50) + '&status=COMPLETED';
  return callAPI(endpoint, 'GET');
}
```

---

## 2. Sidebar.html 수정

### 2.1 RAG 문서 선택 Selectbox 추가

**파일:** [frontend/src/Sidebar.html](file:///c:/Users/imtae/madcamp/2025Winter_4th/frontend/src/Sidebar.html)  
**위치:** 속기록 선택 섹션 (Line 474-496) 아래에 추가

#### 변경 전 (현재):

```html
<!-- 속기록 선택 -->
<div class="mb-4">
  <label class="block text-xs text-google-gray mb-1">속기록 *</label>
  <div class="flex gap-2">
    <input 
      type="text" 
      id="transcript-doc-id" 
      name="transcript-doc-id"
      class="flex-1 border border-gray-300 rounded px-3 py-2 text-sm bg-gray-50"
      placeholder="Google Docs ID (필수)"
      readonly
    >
    <button 
      id="pick-transcript-btn"
      class="picker-btn bg-white border border-gray-300 rounded px-3 py-2 hover:bg-gray-50 transition-colors text-sm"
      data-target="transcript-doc-id"
      data-type="doc"
    >
      📂 선택
    </button>
  </div>
  <p id="transcript-doc-name" class="text-xs text-gray-500 mt-1 truncate"></p>
</div>
```

#### 변경 후 (v2.0):

```html
<!-- 속기록 선택 (v2.0: RAG 학습 완료 문서에서 선택) -->
<div class="mb-4">
  <label class="block text-xs text-google-gray mb-1">
    속기록 * 
    <span class="text-blue-500 font-normal">(RAG 학습 완료 필수)</span>
  </label>
  
  <!-- RAG 문서 Selectbox -->
  <select 
    id="source-document-id" 
    name="source-document-id"
    class="w-full border border-gray-300 rounded px-3 py-2 text-sm mb-2"
  >
    <option value="">-- 속기록 문서 선택 --</option>
    <!-- 동적으로 채워짐 -->
  </select>
  
  <!-- 선택된 문서 정보 -->
  <p id="source-doc-info" class="text-xs text-gray-500 truncate"></p>
  
  <!-- RAG 학습 안내 -->
  <div id="rag-learning-guide" class="hidden mt-2 p-2 bg-yellow-50 border border-yellow-200 rounded text-xs">
    <p class="text-yellow-700">
      ⚠️ 문서가 목록에 없으면 먼저 
      <a href="#" id="go-to-admin-btn" class="text-blue-600 underline">Admin 탭</a>
      에서 RAG 자료학습을 진행해주세요.
    </p>
  </div>
  
  <!-- 새로고침 버튼 -->
  <button 
    id="refresh-rag-docs-btn"
    class="text-xs text-google-blue hover:underline mt-1"
  >
    🔄 문서 목록 새로고침
  </button>
</div>

<!-- 기존 Picker 방식 (Fallback용, 숨김 처리 또는 제거) -->
<div class="mb-4 hidden" id="legacy-transcript-picker">
  <label class="block text-xs text-google-gray mb-1">속기록 (레거시)</label>
  <div class="flex gap-2">
    <input 
      type="text" 
      id="transcript-doc-id" 
      name="transcript-doc-id"
      class="flex-1 border border-gray-300 rounded px-3 py-2 text-sm bg-gray-50"
      placeholder="Google Docs ID"
      readonly
    >
    <button 
      id="pick-transcript-btn"
      class="picker-btn bg-white border border-gray-300 rounded px-3 py-2 hover:bg-gray-50 transition-colors text-sm"
      data-target="transcript-doc-id"
      data-type="doc"
    >
      📂 선택
    </button>
  </div>
</div>
```

### 2.2 JavaScript 로직 추가

**파일:** [frontend/src/Scripts.html](file:///c:/Users/imtae/madcamp/2025Winter_4th/frontend/src/Scripts.html) 또는 [Sidebar.html](file:///c:/Users/imtae/madcamp/2025Winter_4th/frontend/src/Sidebar.html) 내 `<script>` 태그

```javascript
/**
 * RAG 문서 목록 로드
 */
function loadRagDocuments() {
  const select = document.getElementById('source-document-id');
  const info = document.getElementById('source-doc-info');
  const guide = document.getElementById('rag-learning-guide');
  
  // 로딩 표시
  select.innerHTML = '<option value="">로딩 중...</option>';
  select.disabled = true;
  
  google.script.run
    .withSuccessHandler(function(result) {
      select.disabled = false;
      
      if (!result.success) {
        select.innerHTML = '<option value="">⚠️ 목록 조회 실패</option>';
        info.textContent = result.error || '알 수 없는 오류';
        return;
      }
      
      const documents = result.data.documents || [];
      
      if (documents.length === 0) {
        select.innerHTML = '<option value="">RAG 학습된 문서가 없습니다</option>';
        guide.classList.remove('hidden');
        return;
      }
      
      // 옵션 생성
      let options = '<option value="">-- 속기록 문서 선택 --</option>';
      documents.forEach(function(doc) {
        // 문서 유형 아이콘
        const icon = doc.doc_type === 'transcript' ? '📝' : '📄';
        const dateStr = doc.updated_at ? formatDate(new Date(doc.updated_at), 'MM/DD') : '';
        options += `<option value="${doc.id}" data-name="${doc.file_name}" data-date="${dateStr}">${icon} ${doc.file_name} (${dateStr})</option>`;
      });
      
      select.innerHTML = options;
      guide.classList.add('hidden');
    })
    .withFailureHandler(function(error) {
      select.disabled = false;
      select.innerHTML = '<option value="">⚠️ 오류 발생</option>';
      info.textContent = error.message || '서버 연결 실패';
    })
    .apiGetRagDocuments(0, 100);
}

/**
 * 결과지 생성 버튼 클릭 핸들러 (v2.0)
 */
function handleGenerateMinutes() {
  const agendaDocId = document.getElementById('agenda-doc-id').value;
  const sourceDocumentId = document.getElementById('source-document-id').value;
  const meetingName = document.getElementById('meeting-name').value;
  const meetingDate = document.getElementById('meeting-date').value;
  
  // 필수 필드 검증
  if (!agendaDocId) {
    showToast('안건지를 선택해주세요.', 'error');
    return;
  }
  if (!sourceDocumentId) {
    showToast('속기록을 선택해주세요. RAG 자료학습된 문서만 사용 가능합니다.', 'error');
    return;
  }
  if (!meetingName) {
    showToast('회의명을 입력해주세요.', 'error');
    return;
  }
  if (!meetingDate) {
    showToast('회의일자를 선택해주세요.', 'error');
    return;
  }
  
  // v2.0 파라미터
  const params = {
    agendaDocId: agendaDocId,
    sourceDocumentId: parseInt(sourceDocumentId),  // int로 변환
    templateDocId: document.getElementById('template-doc-id').value || null,
    meetingName: meetingName,
    meetingDate: meetingDate,
    outputFolderId: document.getElementById('output-folder-id').value || null,
    userLevel: getUserLevel().level
  };
  
  // API 호출
  google.script.run
    .withSuccessHandler(handleGenerateMinutesResponse)
    .withFailureHandler(handleGenerateMinutesError)
    .apiGenerateMinutes(params);
    
  // 로딩 상태 표시
  showMinutesProgress();
}

/**
 * API 응답 처리
 */
function handleGenerateMinutesResponse(result) {
  if (!result.success) {
    // 에러 메시지 표시
    const errorMessage = result.error || 'Unknown error';
    
    // RAG 학습 필요 에러 특별 처리
    if (errorMessage.includes('RAG') || errorMessage.includes('자료학습')) {
      showToast('⚠️ ' + errorMessage, 'warning', 5000);
      document.getElementById('rag-learning-guide').classList.remove('hidden');
    } else {
      showToast('❌ ' + errorMessage, 'error');
    }
    
    hideMinutesProgress();
    return;
  }
  
  // 성공: task_id로 상태 폴링 시작
  const taskId = result.data.task_id;
  startPollingMinutesStatus(taskId);
}

/**
 * 에러 처리
 */
function handleGenerateMinutesError(error) {
  hideMinutesProgress();
  showToast('❌ 서버 오류: ' + (error.message || error), 'error');
}

// 페이지 로드 시 RAG 문서 목록 로드
document.addEventListener('DOMContentLoaded', function() {
  loadRagDocuments();
  
  // 새로고침 버튼
  document.getElementById('refresh-rag-docs-btn').addEventListener('click', function(e) {
    e.preventDefault();
    loadRagDocuments();
  });
  
  // Admin 탭 이동
  document.getElementById('go-to-admin-btn').addEventListener('click', function(e) {
    e.preventDefault();
    switchTab('admin');
  });
});
```

---

## 3. 에러 Toast 메시지 개선

### 3.1 Toast 스타일 (이미 존재하면 확인)

```css
/* Toast 색상별 스타일 */
.toast.error {
  background: #f8d7da;
  border-color: #f5c6cb;
  color: #721c24;
}
.toast.warning {
  background: #fff3cd;
  border-color: #ffeeba;
  color: #856404;
}
.toast.success {
  background: #d4edda;
  border-color: #c3e6cb;
  color: #155724;
}
```

### 3.2 Toast 함수 (이미 존재하면 확인)

```javascript
function showToast(message, type, duration) {
  const toast = document.createElement('div');
  toast.className = `toast toast-enter ${type || 'info'}`;
  toast.textContent = message;
  
  document.body.appendChild(toast);
  
  setTimeout(() => {
    toast.classList.remove('toast-enter');
    toast.classList.add('toast-exit');
    setTimeout(() => toast.remove(), 300);
  }, duration || 3000);
}
```

---

## 4. 테스트 체크리스트

1. [ ] RAG 문서 목록이 Selectbox에 정상 로드되는지 확인
2. [ ] 문서 선택 없이 "결과지 생성" 클릭 시 에러 메시지 표시 확인
3. [ ] RAG 학습되지 않은 상태에서 안내 메시지 표시 확인
4. [ ] 정상 요청 시 백엔드 응답 확인 (422 에러 없음)
5. [ ] Task 상태 폴링 및 결과 표시 확인

---

## 5. 배포 노트

### Backend 변경 사항 (이미 완료)
- [features_dto.py](file:///c:/Users/imtae/madcamp/2025Winter_4th/backend/app/schemas/features_dto.py): `source_document_id` 필수화
- [features.py](file:///c:/Users/imtae/madcamp/2025Winter_4th/backend/app/tasks/features.py): 4-Phase 아키텍처 구현
- [minutes_control.py](file:///c:/Users/imtae/madcamp/2025Winter_4th/backend/app/api/v1/minutes_control.py): v2.0 API 문서 업데이트

### Frontend 변경 필요
- [Utils.gs](file:///c:/Users/imtae/madcamp/2025Winter_4th/frontend/src/Utils.gs): [apiGenerateMinutes()](file:///c:/Users/imtae/madcamp/2025Winter_4th/frontend/src/Utils.gs#215-273) 수정
- [Sidebar.html](file:///c:/Users/imtae/madcamp/2025Winter_4th/frontend/src/Sidebar.html): RAG 문서 선택 UI 추가

### 배포 순서
1. ✅ Backend 배포 (완료)
2. ⏳ Frontend 수정 및 배포
3. ⏳ Celery Worker 재시작
4. ⏳ E2E 테스트

> **주의:** Frontend 수정 없이 Backend만 배포하면 기존 사용자의 Smart Minutes 기능이 동작하지 않습니다.
