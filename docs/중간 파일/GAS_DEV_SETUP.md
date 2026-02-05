# Council-AI Frontend 로컬 개발 환경 설정 가이드

> **Version:** 2.0.0  
> **Last Updated:** 2026-02-02

이 문서는 Google Apps Script (GAS) 프론트엔드의 로컬 개발 환경 설정 방법을 설명합니다.

---

## 📋 사전 요구사항

- Node.js 18+ 설치
- Google 계정 (Google Workspace 권장)
- GCP 프로젝트 (API Key 발급용)

---

## 1. clasp 설치 및 로그인

### 1.1 clasp 전역 설치

```bash
npm install -g @google/clasp
```

### 1.2 Google 계정 로그인

```bash
clasp login
```

브라우저가 열리면 Google 계정으로 로그인하고 권한을 승인합니다.

---

## 2. 프로젝트 설정

### 2.1 Script ID 확인

1. [Google Apps Script](https://script.google.com) 접속
2. 새 프로젝트 생성 또는 기존 프로젝트 열기
3. **프로젝트 설정** (⚙️) → **Script ID** 복사

### 2.2 clasp.json 수정

`frontend/clasp.json` 파일에서 `scriptId`를 실제 값으로 교체:

```json
{
  "scriptId": "YOUR_ACTUAL_SCRIPT_ID_HERE",
  "rootDir": "./src"
}
```

---

## 3. GCP 프로젝트 연동

### 3.1 GCP 프로젝트 생성/선택

1. [Google Cloud Console](https://console.cloud.google.com) 접속
2. 새 프로젝트 생성 또는 기존 프로젝트 선택

### 3.2 필요한 API 활성화

GCP Console > **APIs & Services** > **Library**에서 다음 API 활성화:

- ✅ Google Drive API
- ✅ Google Docs API
- ✅ Google Calendar API
- ✅ Google Picker API

### 3.3 Apps Script 프로젝트와 GCP 연동

1. Apps Script 에디터 열기
2. **프로젝트 설정** (⚙️) 클릭
3. **Google Cloud Platform(GCP) 프로젝트** 섹션
4. **프로젝트 변경** 클릭
5. GCP 프로젝트 번호 입력 (숫자)

### 3.4 API Key 발급 (Picker용)

1. GCP Console > **APIs & Services** > **Credentials**
2. **CREATE CREDENTIALS** > **API key**
3. 생성된 API Key 복사
4. (선택) **API 제한** 설정: Google Picker API만 허용

---

## 4. 개발 워크플로우

### 4.1 코드 Push (로컬 → GAS)

```bash
cd frontend
clasp push
```

> **주의:** `--watch` 옵션으로 실시간 동기화 가능
> ```bash
> clasp push --watch
> ```

### 4.2 코드 Pull (GAS → 로컬)

```bash
clasp pull
```

### 4.3 Apps Script 에디터 열기

```bash
clasp open
```

### 4.4 웹앱 배포

```bash
clasp deploy --description "v1.0.0"
```

---

## 5. 테스트 방법

### 5.1 사이드바 테스트

1. Google Docs 새 문서 열기
2. **확장 프로그램** > **Apps Script** 실행
3. 또는 직접 URL: `https://docs.google.com/document/d/YOUR_DOC_ID/edit`
4. **확장 프로그램** > **Council-AI** > **사이드바 열기**

### 5.2 로그 확인

```bash
clasp logs
```

또는 Apps Script 에디터에서 **실행** > **실행 로그** 확인

---

## 6. 환경 변수 설정

### 6.1 Script Properties 설정

Apps Script 에디터에서:

1. **프로젝트 설정** (⚙️) 클릭
2. **스크립트 속성** 섹션
3. 다음 속성 추가:

| 속성 이름 | 값 | 설명 |
|----------|-----|------|
| `API_BASE_URL` | `https://your-backend.com/api/v1` | 백엔드 API URL |
| `API_KEY` | `your-api-key` | 백엔드 API Key |
| `PICKER_API_KEY` | `your-picker-api-key` | Google Picker API Key |

### 6.2 또는 코드로 설정

```javascript
function setupProperties() {
  const props = PropertiesService.getScriptProperties();
  props.setProperties({
    'API_BASE_URL': 'https://your-backend.com/api/v1',
    'API_KEY': 'your-api-key',
    'PICKER_API_KEY': 'your-picker-api-key'
  });
}
```

---

## 7. 트러블슈팅

### 7.1 "Authorization required" 오류

**해결:** 
1. Apps Script 에디터에서 함수 실행
2. 권한 승인 팝업에서 **고급** > **안전하지 않은 페이지로 이동** 클릭
3. 권한 승인

### 7.2 Picker가 작동하지 않음

**확인 사항:**
1. GCP 프로젝트에 Picker API 활성화 여부
2. `PICKER_API_KEY` 설정 여부
3. OAuth 토큰이 정상적으로 발급되는지 확인

### 7.3 API 호출 실패

**확인 사항:**
1. `API_BASE_URL` 정확한지 확인 (끝에 `/` 없이)
2. `API_KEY` 설정 여부
3. 백엔드 서버가 실행 중인지 확인
4. CORS 설정 확인

### 7.4 clasp push 실패

**해결:**
```bash
# 다시 로그인
clasp login --creds creds.json

# 또는 로그아웃 후 재로그인
clasp logout
clasp login
```

---

## 8. 프로젝트 구조

```
frontend/
├── clasp.json           # clasp 설정 (Script ID)
├── appsscript.json      # GAS 매니페스트 (OAuth scopes)
└── src/
    ├── Code.gs          # 메인 서버 사이드 코드
    ├── Utils.gs         # API 호출 유틸리티
    ├── Sidebar.html     # 메인 사이드바 UI
    ├── Scripts.html     # 클라이언트 JavaScript
    └── Settings.html    # 설정 다이얼로그
```

---

## 9. 유용한 명령어

```bash
# clasp 버전 확인
clasp --version

# 현재 로그인 상태 확인
clasp status

# 배포 목록 확인
clasp deployments

# 특정 버전 배포
clasp deploy -i <deploymentId> -d "Description"

# 배포 삭제
clasp undeploy <deploymentId>

# 프로젝트 생성
clasp create --title "Council-AI" --type docs
```

---

## 10. 다음 단계

Phase 1 완료 후:

1. **Phase 2:** RAG Chat 연동 및 Markdown 렌더링
2. **Phase 3:** Google Picker + Async Polling 구현
3. **Phase 4:** Calendar Human-in-the-Loop + UX 개선

---

## 📞 지원

문제가 발생하면:

1. `clasp logs`로 로그 확인
2. Chrome DevTools (F12) > Console 확인
3. [Apps Script 공식 문서](https://developers.google.com/apps-script) 참조
