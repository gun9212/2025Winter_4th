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

// ============================================
// Google Calendar (GAS Native)
// ============================================

/**
 * 캘린더 이벤트 생성 (GAS Native - Backend 우회)
 * 
 * 팀 캘린더(Shared Calendar)에 이벤트를 등록합니다.
 * 사용자에게 해당 캘린더에 대한 쓰기 권한(WRITER/OWNER)이 필요합니다.
 * 
 * @param {Object} eventData - 이벤트 데이터
 * @param {string} eventData.summary - 이벤트 제목
 * @param {string} eventData.dtStart - 시작 시간 (ISO String)
 * @param {string} eventData.dtEnd - 종료 시간 (ISO String)
 * @param {string} [eventData.description] - 이벤트 설명
 * @param {string} [eventData.assigneeEmail] - 담당자 이메일 (게스트로 초대)
 * @param {string} [eventData.calendarId] - 캘린더 ID (기본값: primary)
 * @returns {Object} 결과 { success, eventId, htmlLink, error }
 */
function createCalendarEvent(eventData) {
  try {
    // 1. 캘린더 ID 결정 (기본값: primary)
    const calendarId = eventData.calendarId || 'primary';
    
    // 2. 캘린더 객체 획득
    let calendar;
    if (calendarId === 'primary') {
      calendar = CalendarApp.getDefaultCalendar();
    } else {
      calendar = CalendarApp.getCalendarById(calendarId);
    }
    
    if (!calendar) {
      throw new Error(`캘린더를 찾을 수 없습니다: ${calendarId}`);
    }
    
    const calendarName = calendar.getName();
    
    // 3. 시간 파싱 (ISO String → Date)
    const startTime = new Date(eventData.dtStart);
    const endTime = new Date(eventData.dtEnd);
    
    // 시간 유효성 검사
    if (isNaN(startTime.getTime()) || isNaN(endTime.getTime())) {
      throw new Error('유효하지 않은 날짜 형식입니다.');
    }
    
    if (endTime <= startTime) {
      throw new Error('종료 시간은 시작 시간보다 이후여야 합니다.');
    }
    
    // 4. 이벤트 옵션 구성
    const options = {};
    
    // 설명 추가
    if (eventData.description) {
      options.description = eventData.description;
    }
    
    // 담당자를 게스트로 초대 (유효한 이메일인 경우)
    if (eventData.assigneeEmail && isValidEmailAddress(eventData.assigneeEmail)) {
      options.guests = eventData.assigneeEmail;
      options.sendInvites = true; // 초대 이메일 발송
    }
    
    // 5. 이벤트 생성 (권한이 없으면 여기서 예외 발생)
    const event = calendar.createEvent(
      eventData.summary,
      startTime,
      endTime,
      options
    );
    
    // 6. 결과 반환
    const eventId = event.getId();
    
    // Google Calendar 웹 링크 생성
    const encodedEventId = Utilities.base64Encode(eventId + ' ' + calendarId);
    const htmlLink = `https://calendar.google.com/calendar/event?eid=${encodedEventId}`;
    
    Logger.log(`이벤트 생성 성공: ${eventData.summary} → ${calendarName}`);
    
    return {
      success: true,
      eventId: eventId,
      htmlLink: htmlLink,
      calendarName: calendarName,
      summary: eventData.summary,
      startTime: startTime.toISOString(),
      endTime: endTime.toISOString()
    };
    
  } catch (error) {
    Logger.log(`이벤트 생성 실패: ${error.message}`);
    
    // 권한 관련 에러 메시지 개선
    let errorMessage = error.message;
    if (errorMessage.includes('denied') || errorMessage.includes('permission') || 
        errorMessage.includes('액세스') || errorMessage.includes('권한')) {
      errorMessage = `캘린더에 쓰기 권한이 없습니다. 캘린더 관리자에게 권한을 요청하세요.\n(원본 오류: ${error.message})`;
    }
    
    return {
      success: false,
      error: errorMessage
    };
  }
}

/**
 * 이메일 주소 유효성 검사
 * @param {string} email - 이메일 주소
 * @returns {boolean} 유효 여부
 */
function isValidEmailAddress(email) {
  if (!email || typeof email !== 'string') return false;
  const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
  return emailRegex.test(email.trim());
}

/**
 * 캘린더 접근 권한 확인 (테스트용)
 * 
 * 실제 이벤트 생성을 시도하여 권한을 확인합니다.
 * (GAS 기본 CalendarApp에서는 권한 레벨을 직접 조회할 수 없음)
 * 
 * @param {string} calendarId - 캘린더 ID
 * @returns {Object} 권한 정보
 */
function checkCalendarAccess(calendarId) {
  try {
    const calendar = calendarId === 'primary' 
      ? CalendarApp.getDefaultCalendar()
      : CalendarApp.getCalendarById(calendarId);
    
    if (!calendar) {
      return {
        success: false,
        error: `캘린더를 찾을 수 없습니다: ${calendarId}`
      };
    }
    
    const calendarName = calendar.getName();
    const isOwned = calendar.isOwnedByMe();
    
    // 테스트 이벤트 생성 시도 (즉시 삭제)
    let canWrite = false;
    try {
      const now = new Date();
      const testEvent = calendar.createEvent(
        '[테스트] 권한 확인용 - 자동 삭제됨',
        now,
        new Date(now.getTime() + 60000) // 1분 후
      );
      testEvent.deleteEvent(); // 즉시 삭제
      canWrite = true;
    } catch (writeError) {
      canWrite = false;
    }
    
    return {
      success: true,
      calendarId: calendarId,
      calendarName: calendarName,
      accessLevel: isOwned ? 'OWNER' : (canWrite ? 'WRITER' : 'READ_ONLY'),
      canWrite: canWrite,
      isOwner: isOwned
    };
  } catch (error) {
    return {
      success: false,
      error: error.message
    };
  }
}

/**
 * 사용자가 접근 가능한 모든 캘린더 목록 조회
 * @returns {Array} 캘린더 목록
 */
function getAccessibleCalendars() {
  try {
    const calendars = CalendarApp.getAllCalendars();
    
    return calendars.map(function(cal) {
      const isOwned = cal.isOwnedByMe();
      return {
        id: cal.getId(),
        name: cal.getName(),
        isOwned: isOwned,
        // 소유자가 아닌 경우 쓰기 권한은 실제 시도해봐야 알 수 있음
        // 여기서는 소유자 여부만 표시
        accessLevel: isOwned ? 'OWNER' : 'UNKNOWN',
        color: cal.getColor()
      };
    }).sort(function(a, b) {
      // 소유한 캘린더를 먼저 정렬
      if (a.isOwned && !b.isOwned) return -1;
      if (!a.isOwned && b.isOwned) return 1;
      return a.name.localeCompare(b.name);
    });
  } catch (error) {
    Logger.log('캘린더 목록 조회 실패: ' + error.message);
    return [];
  }
}
