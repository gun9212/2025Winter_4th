/**
 * ========================================
 * Council-AI Google Apps Script
 * 학생회 업무 자동화 사이드바 애드온
 * Version: 2.0.0
 * ========================================
 */

// ============================================
// 전역 설정
// ============================================

/**
 * 설정값을 가져옵니다.
 * @returns {Object} 설정 객체
 */
function getConfig() {
  const props = PropertiesService.getScriptProperties();
  return {
    API_BASE_URL: props.getProperty('API_BASE_URL') || 'http://localhost:8000/api/v1',
    API_KEY: props.getProperty('API_KEY') || '',
    PICKER_API_KEY: props.getProperty('PICKER_API_KEY') || ''
  };
}

// ============================================
// 문서 메뉴 및 사이드바
// ============================================

/**
 * 문서 열기 시 메뉴 추가
 */
function onOpen() {
  DocumentApp.getUi()
    .createAddonMenu()
    .addItem('🚀 사이드바 열기', 'showSidebar')
    .addSeparator()
    .addItem('⚙️ 설정', 'showSettingsDialog')
    .addToUi();
}

/**
 * 애드온 설치 시 호출
 */
function onInstall() {
  onOpen();
}

/**
 * 홈페이지 트리거 (Add-on용)
 */
function onHomepage() {
  return createHomepageCard();
}

/**
 * 파일 스코프 승인 후 트리거
 */
function onFileScopeGranted() {
  return createHomepageCard();
}

/**
 * 홈페이지 카드 생성
 */
function createHomepageCard() {
  const card = CardService.newCardBuilder()
    .setHeader(CardService.newCardHeader().setTitle('Council-AI'))
    .addSection(
      CardService.newCardSection()
        .addWidget(
          CardService.newTextButton()
            .setText('사이드바 열기')
            .setOnClickAction(CardService.newAction().setFunctionName('showSidebar'))
        )
    )
    .build();
  return card;
}

/**
 * 사이드바 표시
 */
function showSidebar() {
  const html = HtmlService.createTemplateFromFile('Sidebar')
    .evaluate()
    .setTitle('Council-AI')
    .setWidth(380);
  DocumentApp.getUi().showSidebar(html);
}

/**
 * 설정 다이얼로그 표시
 */
function showSettingsDialog() {
  const html = HtmlService.createHtmlOutputFromFile('Settings')
    .setWidth(450)
    .setHeight(400);
  DocumentApp.getUi().showModalDialog(html, '⚙️ Council-AI 설정');
}

/**
 * HTML 파일 포함 (템플릿용)
 * @param {string} filename - 포함할 파일명
 * @returns {string} HTML 콘텐츠
 */
function include(filename) {
  return HtmlService.createHtmlOutputFromFile(filename).getContent();
}

// ============================================
// 사용자 정보
// ============================================

/**
 * 현재 사용자 이메일 가져오기
 * @returns {string} 이메일
 */
function getCurrentUserEmail() {
  return Session.getActiveUser().getEmail();
}

/**
 * 현재 문서 ID 가져오기
 * @returns {string} 문서 ID
 */
function getCurrentDocumentId() {
  const doc = DocumentApp.getActiveDocument();
  return doc ? doc.getId() : null;
}

/**
 * 현재 문서 이름 가져오기
 * @returns {string} 문서 이름
 */
function getCurrentDocumentName() {
  const doc = DocumentApp.getActiveDocument();
  return doc ? doc.getName() : null;
}

/**
 * 현재 문서 내용 가져오기
 * @returns {string} 문서 텍스트 내용
 */
function getCurrentDocumentText() {
  const doc = DocumentApp.getActiveDocument();
  return doc ? doc.getBody().getText() : '';
}

// ============================================
// Google Picker 관련
// ============================================

/**
 * OAuth 토큰 가져오기 (Picker용)
 * @returns {string} OAuth 토큰
 */
function getOAuthToken() {
  return ScriptApp.getOAuthToken();
}

/**
 * Picker API 설정 가져오기
 * @returns {Object} Picker 설정
 */
function getPickerConfig() {
  const config = getConfig();
  return {
    developerKey: config.PICKER_API_KEY,
    oauthToken: ScriptApp.getOAuthToken(),
    appId: ScriptApp.getProjectKey()
  };
}

// ============================================
// 상태 저장/복원 (PropertiesService)
// ============================================

/**
 * 사용자 설정 저장
 * @param {string} key - 키
 * @param {string} value - 값
 */
function saveUserProperty(key, value) {
  PropertiesService.getUserProperties().setProperty(key, value);
}

/**
 * 사용자 설정 가져오기
 * @param {string} key - 키
 * @returns {string} 값
 */
function getUserProperty(key) {
  return PropertiesService.getUserProperties().getProperty(key);
}

/**
 * 사용자 설정 삭제
 * @param {string} key - 키
 */
function deleteUserProperty(key) {
  PropertiesService.getUserProperties().deleteProperty(key);
}

/**
 * 모든 사용자 설정 가져오기
 * @returns {Object} 모든 설정
 */
function getAllUserProperties() {
  return PropertiesService.getUserProperties().getProperties();
}

/**
 * 채팅 세션 ID 저장
 * @param {string} sessionId - 세션 ID
 */
function saveChatSessionId(sessionId) {
  saveUserProperty('chat_session_id', sessionId);
}

/**
 * 채팅 세션 ID 가져오기
 * @returns {string} 세션 ID
 */
function getChatSessionId() {
  return getUserProperty('chat_session_id');
}

// ============================================
// 관리자 설정 (ScriptProperties)
// ============================================

/**
 * API 설정 저장 (관리자용)
 * @param {Object} settings - 설정 객체
 * @returns {Object} 결과
 */
function saveAdminSettings(settings) {
  try {
    const props = PropertiesService.getScriptProperties();
    
    if (settings.apiBaseUrl) {
      props.setProperty('API_BASE_URL', settings.apiBaseUrl);
    }
    if (settings.apiKey) {
      props.setProperty('API_KEY', settings.apiKey);
    }
    if (settings.pickerApiKey) {
      props.setProperty('PICKER_API_KEY', settings.pickerApiKey);
    }
    
    return { success: true, message: '설정이 저장되었습니다.' };
  } catch (error) {
    return { success: false, error: error.message };
  }
}

/**
 * 관리자 설정 가져오기
 * @returns {Object} 설정 (마스킹됨)
 */
function getAdminSettings() {
  const config = getConfig();
  return {
    apiBaseUrl: config.API_BASE_URL,
    apiKey: config.API_KEY ? '********' + config.API_KEY.slice(-4) : '',
    pickerApiKey: config.PICKER_API_KEY ? '********' + config.PICKER_API_KEY.slice(-4) : '',
    hasApiKey: !!config.API_KEY,
    hasPickerApiKey: !!config.PICKER_API_KEY
  };
}

// ============================================
// 템플릿 검사 (클라이언트 사이드 지원)
// ============================================

/**
 * 문서에서 Placeholder 추출
 * @param {string} docId - Google Docs ID
 * @returns {Object} Placeholder 목록
 */
function extractPlaceholders(docId) {
  try {
    const doc = DocumentApp.openById(docId);
    const text = doc.getBody().getText();
    
    // {{...}} 패턴 찾기
    const regex = /\{\{([^}]+)\}\}/g;
    const placeholders = [];
    let match;
    
    while ((match = regex.exec(text)) !== null) {
      placeholders.push({
        full: match[0],
        name: match[1].trim(),
        index: match.index
      });
    }
    
    // 중복 제거
    const uniqueNames = [...new Set(placeholders.map(p => p.name))];
    
    return {
      success: true,
      placeholders: placeholders,
      uniqueNames: uniqueNames,
      count: uniqueNames.length,
      documentName: doc.getName()
    };
  } catch (error) {
    return {
      success: false,
      error: error.message
    };
  }
}

// ============================================
// 문서 URL 생성
// ============================================

/**
 * Google Docs URL 생성
 * @param {string} docId - 문서 ID
 * @returns {string} URL
 */
function getDocumentUrl(docId) {
  return `https://docs.google.com/document/d/${docId}/edit`;
}

/**
 * Google Drive 폴더 URL 생성
 * @param {string} folderId - 폴더 ID
 * @returns {string} URL
 */
function getFolderUrl(folderId) {
  return `https://drive.google.com/drive/folders/${folderId}`;
}
