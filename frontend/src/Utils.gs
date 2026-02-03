/**
 * ========================================
 * Council-AI Utilities
 * API 호출 및 유틸리티 함수
 * Version: 2.0.0
 * ========================================
 */

// ============================================
// API 호출 래퍼
// ============================================

/**
 * 백엔드 API 호출 (X-API-Key 자동 주입)
 * @param {string} endpoint - API 엔드포인트 (예: '/chat')
 * @param {string} method - HTTP 메서드 ('GET', 'POST', 'PUT', 'DELETE')
 * @param {Object} payload - 요청 데이터 (선택)
 * @param {Object} options - 추가 옵션 (선택)
 * @returns {Object} API 응답 { success, data, error, statusCode }
 */
function callAPI(endpoint, method, payload, options) {
  const config = getConfig();
  const url = config.API_BASE_URL + endpoint;
  
  const fetchOptions = {
    method: method || 'GET',
    contentType: 'application/json',
    headers: {
      'X-API-Key': config.API_KEY,
      'Accept': 'application/json'
    },
    muteHttpExceptions: true,
    ...options
  };
  
  // POST/PUT 요청 시 payload 추가
  if (payload && (method === 'POST' || method === 'PUT' || method === 'PATCH')) {
    fetchOptions.payload = JSON.stringify(payload);
  }
  
  try {
    const response = UrlFetchApp.fetch(url, fetchOptions);
    const responseCode = response.getResponseCode();
    const responseText = response.getContentText();
    
    // 성공 응답 (2xx)
    if (responseCode >= 200 && responseCode < 300) {
      let data = null;
      try {
        data = responseText ? JSON.parse(responseText) : null;
      } catch (e) {
        data = responseText;
      }
      
      return {
        success: true,
        data: data,
        statusCode: responseCode
      };
    }
    
    // 에러 응답
    let errorData = null;
    try {
      errorData = JSON.parse(responseText);
    } catch (e) {
      errorData = { detail: responseText };
    }
    
    // FastAPI validation error는 detail이 배열 형태
    // 예: [{"loc": ["body", "meeting_date"], "msg": "...", "type": "..."}]
    let errorMessage = responseText;
    if (errorData.detail) {
      if (Array.isArray(errorData.detail)) {
        // Validation 에러 배열을 읽기 쉬운 문자열로 변환
        errorMessage = errorData.detail.map(function(err) {
          const field = err.loc ? err.loc.slice(1).join('.') : 'unknown';
          return field + ': ' + (err.msg || err.message || JSON.stringify(err));
        }).join('; ');
      } else if (typeof errorData.detail === 'object') {
        errorMessage = JSON.stringify(errorData.detail);
      } else {
        errorMessage = errorData.detail;
      }
    } else if (errorData.message) {
      errorMessage = errorData.message;
    }
    
    return {
      success: false,
      error: errorMessage,
      errorData: errorData,
      statusCode: responseCode
    };
    
  } catch (error) {
    return {
      success: false,
      error: error.toString(),
      statusCode: 0
    };
  }
}

// ============================================
// Chat API
// ============================================

/**
 * RAG 채팅 API 호출
 * @param {string} query - 사용자 질문
 * @param {string} sessionId - 세션 ID (선택)
 * @param {number} userLevel - 사용자 권한 레벨 (1-4)
 * @param {Object} options - 추가 옵션
 * @returns {Object} 채팅 응답
 */
function apiChat(query, sessionId, userLevel, options) {
  // sessionId가 없으면 새로 생성
  const finalSessionId = sessionId || generateUUID();
  
  const payload = {
    query: query,
    session_id: finalSessionId,
    user_level: userLevel || 4,
    options: options || {
      max_results: 5,
      include_sources: true
    }
  };
  
  return callAPI('/chat', 'POST', payload);
}

/**
 * 채팅 히스토리 조회
 * @param {string} sessionId - 세션 ID
 * @returns {Object} 히스토리
 */
function apiGetChatHistory(sessionId) {
  return callAPI('/chat/history/' + sessionId, 'GET');
}

/**
 * 채팅 히스토리 삭제
 * @param {string} sessionId - 세션 ID
 * @returns {Object} 결과
 */
function apiDeleteChatHistory(sessionId) {
  return callAPI('/chat/history/' + sessionId, 'DELETE');
}

// ============================================
// RAG API
// ============================================

/**
 * 문서 검색 API
 * @param {string} query - 검색어
 * @param {number} topK - 결과 개수
 * @param {boolean} generateAnswer - 답변 생성 여부
 * @returns {Object} 검색 결과
 */
function apiRagSearch(query, topK, generateAnswer) {
  const payload = {
    query: query,
    top_k: topK || 5,
    include_context: true,
    generate_answer: generateAnswer !== false
  };
  
  return callAPI('/rag/search', 'POST', payload);
}

/**
 * 폴더 인제스트 시작
 * @param {string} folderId - Google Drive 폴더 ID
 * @param {Object} options - 인제스트 옵션
 * @param {number} userLevel - 사용자 권한 레벨
 * @returns {Object} task_id 포함 응답
 */
function apiIngestFolder(folderId, options, userLevel) {
  const payload = {
    folder_id: folderId,
    options: options || {
      recursive: true,
      file_types: ['google_doc', 'pdf', 'docx']
    },
    user_level: userLevel || 2
  };
  
  return callAPI('/rag/ingest/folder', 'POST', payload);
}

/**
 * 인덱싱된 문서 목록 조회
 * @param {number} skip - 페이지네이션 오프셋
 * @param {number} limit - 페이지 크기
 * @param {string} status - 상태 필터
 * @returns {Object} 문서 목록
 */
function apiGetDocuments(skip, limit, status) {
  let endpoint = '/rag/documents?skip=' + (skip || 0) + '&limit=' + (limit || 20);
  if (status) {
    endpoint += '&status=' + status;
  }
  return callAPI(endpoint, 'GET');
}

// ============================================
// Smart Minutes API
// ============================================

/**
 * 결과지 생성 요청
 * @param {Object} params - 생성 파라미터
 * @returns {Object} task_id 포함 응답
 * 
 * Backend Validator Note:
 * - transcript_doc_id 또는 transcript_text 중 하나는 반드시 제공해야 함
 * - 둘 다 없으면 422 Validation Error 발생
 * - meeting_date는 'YYYY-MM-DD' 형식의 문자열로 전송 (ISO date)
 */
function apiGenerateMinutes(params) {
  // transcript 소스 검증: doc_id나 text 중 하나는 필수
  const transcriptDocId = params.transcriptDocId && params.transcriptDocId.trim() !== '' 
    ? params.transcriptDocId.trim() 
    : null;
  const transcriptText = params.transcriptText && params.transcriptText.trim() !== ''
    ? params.transcriptText.trim()
    : null;
  
  // 프론트엔드에서 사전 검증 (둘 다 없으면 에러)
  if (!transcriptDocId && !transcriptText) {
    return {
      success: false,
      error: '속기록이 필요합니다. 속기록 문서를 선택하거나 텍스트를 직접 입력해주세요.',
      statusCode: 0
    };
  }
  
  // meeting_date가 Date 객체면 YYYY-MM-DD로 변환
  let meetingDate = params.meetingDate;
  if (meetingDate instanceof Date) {
    meetingDate = formatDate(meetingDate, 'YYYY-MM-DD');
  }
  
  // 현재 사용자 이메일 가져오기 (Service Account 모드에서 파일 공유용)
  const userEmail = Session.getActiveUser().getEmail();
  
  const payload = {
    agenda_doc_id: params.agendaDocId,
    transcript_doc_id: transcriptDocId,
    transcript_text: transcriptText,
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

/**
 * 결과지 생성 상태 조회
 * @param {string} taskId - 작업 ID
 * @returns {Object} 상태 정보
 */
function apiGetMinutesStatus(taskId) {
  return callAPI('/minutes/' + taskId + '/status', 'GET');
}

// ============================================
// Calendar API (Human-in-the-Loop)
// ============================================

/**
 * 할일 추출 (결과지에서)
 * @param {string} resultDocId - 결과지 Google Docs ID
 * @param {boolean} includeContext - 컨텍스트 포함 여부
 * @returns {Object} 할일 목록
 */
function apiExtractTodos(resultDocId, includeContext) {
  const payload = {
    result_doc_id: resultDocId,
    include_context: includeContext !== false
  };
  
  return callAPI('/calendar/extract-todos', 'POST', payload);
}

/**
 * 캘린더 이벤트 생성
 * @param {Object} eventData - 이벤트 데이터
 * @returns {Object} 생성된 이벤트 정보
 */
function apiCreateCalendarEvent(eventData) {
  const payload = {
    summary: eventData.summary,
    dt_start: eventData.dtStart,
    dt_end: eventData.dtEnd,
    description: eventData.description || '',
    assignee_email: eventData.assigneeEmail || null,
    calendar_id: eventData.calendarId || 'primary',
    reminder_minutes: eventData.reminderMinutes || 60,
    source_doc_id: eventData.sourceDocId || null
  };
  
  return callAPI('/calendar/events/create', 'POST', payload);
}

// ============================================
// Handover API
// ============================================

/**
 * 인수인계서 생성 요청
 * @param {Object} params - 생성 파라미터
 * @returns {Object} task_id 포함 응답
 */
function apiGenerateHandover(params) {
  const payload = {
    target_year: params.targetYear,
    department: params.department || null,
    target_folder_id: params.targetFolderId || null,
    doc_title: params.docTitle || null,
    include_event_summaries: params.includeEventSummaries !== false,
    include_insights: params.includeInsights !== false,
    include_statistics: params.includeStatistics !== false,
    user_level: params.userLevel || 1
  };
  
  return callAPI('/handover/generate', 'POST', payload);
}

/**
 * 인수인계서 생성 상태 조회
 * @param {string} taskId - 작업 ID
 * @returns {Object} 상태 정보
 */
function apiGetHandoverStatus(taskId) {
  return callAPI('/handover/' + taskId + '/status', 'GET');
}

// ============================================
// Task API (공통)
// ============================================

/**
 * Task 상태 조회
 * @param {string} taskId - 작업 ID
 * @returns {Object} 상태 정보
 */
function apiGetTaskStatus(taskId) {
  return callAPI('/tasks/' + taskId, 'GET');
}

/**
 * Task 취소
 * @param {string} taskId - 작업 ID
 * @returns {Object} 결과
 */
function apiCancelTask(taskId) {
  return callAPI('/tasks/' + taskId, 'DELETE');
}

// ============================================
// 유틸리티 함수
// ============================================

/**
 * UUID 생성
 * @returns {string} UUID v4
 */
function generateUUID() {
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, function(c) {
    const r = Math.random() * 16 | 0;
    const v = c === 'x' ? r : (r & 0x3 | 0x8);
    return v.toString(16);
  });
}

/**
 * 날짜 포맷팅
 * @param {Date|string} date - 날짜
 * @param {string} format - 포맷 ('YYYY-MM-DD', 'YYYY-MM-DD HH:mm:ss')
 * @returns {string} 포맷된 날짜 문자열
 */
function formatDate(date, format) {
  const d = date instanceof Date ? date : new Date(date);
  
  const year = d.getFullYear();
  const month = String(d.getMonth() + 1).padStart(2, '0');
  const day = String(d.getDate()).padStart(2, '0');
  const hours = String(d.getHours()).padStart(2, '0');
  const minutes = String(d.getMinutes()).padStart(2, '0');
  const seconds = String(d.getSeconds()).padStart(2, '0');
  
  if (format === 'YYYY-MM-DD HH:mm:ss') {
    return `${year}-${month}-${day} ${hours}:${minutes}:${seconds}`;
  }
  
  return `${year}-${month}-${day}`;
}

/**
 * ISO 날짜 문자열 생성
 * @param {Date|string} date - 날짜
 * @returns {string} ISO 형식 날짜 문자열
 */
function toISOString(date) {
  const d = date instanceof Date ? date : new Date(date);
  return d.toISOString();
}

/**
 * 이메일 유효성 검사
 * @param {string} email - 이메일 주소
 * @returns {boolean} 유효 여부
 */
function isValidEmail(email) {
  const regex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
  return regex.test(email);
}

/**
 * 빈 값 체크
 * @param {*} value - 체크할 값
 * @returns {boolean} 빈 값 여부
 */
function isEmpty(value) {
  if (value === null || value === undefined) return true;
  if (typeof value === 'string') return value.trim() === '';
  if (Array.isArray(value)) return value.length === 0;
  if (typeof value === 'object') return Object.keys(value).length === 0;
  return false;
}

/**
 * 에러 로그 기록
 * @param {string} functionName - 함수명
 * @param {Error|string} error - 에러
 */
function logError(functionName, error) {
  const message = error instanceof Error ? error.message : String(error);
  console.error(`[${functionName}] Error: ${message}`);
  
  // 필요시 Stackdriver Logging 사용
  // Logger.log(`[${functionName}] Error: ${message}`);
}

/**
 * 안전한 JSON 파싱
 * @param {string} jsonString - JSON 문자열
 * @param {*} defaultValue - 파싱 실패 시 기본값
 * @returns {*} 파싱된 객체 또는 기본값
 */
function safeJsonParse(jsonString, defaultValue) {
  try {
    return JSON.parse(jsonString);
  } catch (e) {
    return defaultValue !== undefined ? defaultValue : null;
  }
}

/**
 * 객체 깊은 복사
 * @param {Object} obj - 복사할 객체
 * @returns {Object} 복사된 객체
 */
function deepCopy(obj) {
  return JSON.parse(JSON.stringify(obj));
}

/**
 * 텍스트 자르기 (말줄임)
 * @param {string} text - 텍스트
 * @param {number} maxLength - 최대 길이
 * @returns {string} 잘린 텍스트
 */
function truncateText(text, maxLength) {
  if (!text || text.length <= maxLength) return text;
  return text.substring(0, maxLength - 3) + '...';
}
