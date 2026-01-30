/**
 * Council-AI Google Apps Script
 * 학생회 업무 자동화 사이드바 애드온
 */

// Backend API 설정
const CONFIG = {
  API_BASE_URL: 'https://YOUR_BACKEND_URL/api/v1',
  API_KEY: PropertiesService.getScriptProperties().getProperty('API_KEY') || ''
};

/**
 * 문서 열기 시 메뉴 추가
 */
function onOpen() {
  DocumentApp.getUi()
    .createAddonMenu()
    .addItem('사이드바 열기', 'showSidebar')
    .addSeparator()
    .addItem('회의록 생성', 'showMinutesDialog')
    .addItem('지식 검색', 'showSearchDialog')
    .addItem('일정 추출', 'showCalendarDialog')
    .addToUi();
}

/**
 * 설치 시 호출
 */
function onInstall() {
  onOpen();
}

/**
 * 사이드바 표시
 */
function showSidebar() {
  const html = HtmlService.createHtmlOutputFromFile('Sidebar')
    .setTitle('Council-AI')
    .setWidth(350);
  DocumentApp.getUi().showSidebar(html);
}

/**
 * 회의록 다이얼로그 표시
 */
function showMinutesDialog() {
  const html = HtmlService.createHtmlOutputFromFile('Sidebar')
    .setWidth(400)
    .setHeight(500);
  DocumentApp.getUi().showModalDialog(html, '회의록 자동 생성');
}

/**
 * 검색 다이얼로그 표시
 */
function showSearchDialog() {
  const html = HtmlService.createHtmlOutputFromFile('Sidebar')
    .setWidth(400)
    .setHeight(500);
  DocumentApp.getUi().showModalDialog(html, '지식 DB 검색');
}

/**
 * 캘린더 다이얼로그 표시
 */
function showCalendarDialog() {
  const html = HtmlService.createHtmlOutputFromFile('Sidebar')
    .setWidth(400)
    .setHeight(500);
  DocumentApp.getUi().showModalDialog(html, '일정 추출');
}

/**
 * 현재 문서 ID 가져오기
 * @returns {string} 문서 ID
 */
function getCurrentDocumentId() {
  return DocumentApp.getActiveDocument().getId();
}

/**
 * 현재 문서 내용 가져오기
 * @returns {string} 문서 텍스트 내용
 */
function getCurrentDocumentText() {
  const doc = DocumentApp.getActiveDocument();
  return doc.getBody().getText();
}

/**
 * 백엔드 API 호출
 * @param {string} endpoint - API 엔드포인트
 * @param {string} method - HTTP 메서드
 * @param {Object} payload - 요청 데이터
 * @returns {Object} API 응답
 */
function callBackendAPI(endpoint, method, payload) {
  const url = CONFIG.API_BASE_URL + endpoint;

  const options = {
    method: method,
    contentType: 'application/json',
    headers: {
      'X-API-Key': CONFIG.API_KEY
    },
    muteHttpExceptions: true
  };

  if (payload && (method === 'POST' || method === 'PUT')) {
    options.payload = JSON.stringify(payload);
  }

  try {
    const response = UrlFetchApp.fetch(url, options);
    const responseCode = response.getResponseCode();
    const responseText = response.getContentText();

    if (responseCode >= 200 && responseCode < 300) {
      return {
        success: true,
        data: JSON.parse(responseText)
      };
    } else {
      return {
        success: false,
        error: responseText,
        statusCode: responseCode
      };
    }
  } catch (error) {
    return {
      success: false,
      error: error.toString()
    };
  }
}

/**
 * 회의록 처리 요청
 * @param {string} transcript - 속기록/녹취록 텍스트
 * @returns {Object} 처리 결과
 */
function processMinutes(transcript) {
  const documentId = getCurrentDocumentId();

  return callBackendAPI('/minutes/process', 'POST', {
    agenda_doc_id: documentId,
    transcript: transcript
  });
}

/**
 * 회의록 처리 상태 확인
 * @param {string} taskId - 작업 ID
 * @returns {Object} 상태 정보
 */
function getMinutesStatus(taskId) {
  return callBackendAPI('/minutes/' + taskId + '/status', 'GET', null);
}

/**
 * RAG 검색 수행
 * @param {string} query - 검색어
 * @param {number} topK - 결과 개수
 * @returns {Object} 검색 결과
 */
function searchKnowledge(query, topK) {
  return callBackendAPI('/rag/search', 'POST', {
    query: query,
    top_k: topK || 5,
    generate_answer: true
  });
}

/**
 * 문서에서 일정 추출
 * @returns {Object} 추출된 일정 목록
 */
function extractCalendarEvents() {
  const text = getCurrentDocumentText();

  return callBackendAPI('/calendar/extract', 'POST', {
    text: text
  });
}

/**
 * 캘린더에 이벤트 생성
 * @param {Object} event - 이벤트 정보
 * @returns {Object} 생성 결과
 */
function createCalendarEvent(event) {
  return callBackendAPI('/calendar/events', 'POST', event);
}

/**
 * 문서에 텍스트 삽입
 * @param {string} text - 삽입할 텍스트
 * @param {boolean} atCursor - 커서 위치에 삽입 여부
 */
function insertTextToDocument(text, atCursor) {
  const doc = DocumentApp.getActiveDocument();
  const body = doc.getBody();

  if (atCursor) {
    const cursor = doc.getCursor();
    if (cursor) {
      cursor.insertText(text);
    } else {
      body.appendParagraph(text);
    }
  } else {
    body.appendParagraph(text);
  }
}

/**
 * 검색 결과를 문서에 삽입
 * @param {string} answer - AI 생성 답변
 * @param {Array} sources - 소스 문서 목록
 */
function insertSearchResult(answer, sources) {
  const doc = DocumentApp.getActiveDocument();
  const body = doc.getBody();

  // 답변 삽입
  const answerPara = body.appendParagraph(answer);
  answerPara.setHeading(DocumentApp.ParagraphHeading.NORMAL);

  // 소스 삽입
  if (sources && sources.length > 0) {
    const sourcePara = body.appendParagraph('\n참고 문서:');
    sourcePara.setBold(true);

    sources.forEach(function(source) {
      const link = body.appendParagraph('• ' + source.document_name);
      if (source.url) {
        link.setLinkUrl(source.url);
      }
    });
  }
}
