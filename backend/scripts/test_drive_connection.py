"""
Drive API 연결 테스트 및 실제 파일 목록 확인
"""
import os
import sys

# 프로젝트 루트 추가
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from google.oauth2 import service_account
from googleapiclient.discovery import build

# 서비스 계정 인증
SCOPES = [
    'https://www.googleapis.com/auth/drive.readonly',
    'https://www.googleapis.com/auth/documents.readonly',
]

CREDENTIALS_PATH = "/app/credentials/google_key.json"
FOLDER_ID = os.getenv("GOOGLE_DRIVE_FOLDER_ID", "1ETM-wy_27q58MXUvMF3fglSZ7zuvtyZb")

def main():
    print("=" * 60)
    print("🔍 Google Drive API 연결 테스트")
    print("=" * 60)
    
    # 1. 인증
    print("\n[1] 서비스 계정 인증 중...")
    try:
        credentials = service_account.Credentials.from_service_account_file(
            CREDENTIALS_PATH, scopes=SCOPES
        )
        print(f"  ✅ 인증 성공: {credentials.service_account_email}")
    except Exception as e:
        print(f"  ❌ 인증 실패: {e}")
        return
    
    # 2. Drive API 빌드
    print("\n[2] Drive API 연결 중...")
    try:
        service = build('drive', 'v3', credentials=credentials)
        print("  ✅ Drive API 연결 성공")
    except Exception as e:
        print(f"  ❌ Drive API 연결 실패: {e}")
        return
    
    # 3. 폴더 접근 테스트
    print(f"\n[3] 폴더 접근 테스트 (ID: {FOLDER_ID})")
    try:
        # 폴더 메타데이터 가져오기
        folder = service.files().get(
            fileId=FOLDER_ID,
            fields="id, name, mimeType"
        ).execute()
        print(f"  ✅ 폴더 접근 성공: {folder.get('name')}")
    except Exception as e:
        print(f"  ❌ 폴더 접근 실패: {e}")
        print("  💡 서비스 계정에 폴더 공유가 필요합니다!")
        return
    
    # 4. 폴더 내 파일 목록 (상위 레벨만)
    print(f"\n[4] 폴더 내 파일/폴더 목록 (상위 10개)")
    try:
        results = service.files().list(
            q=f"'{FOLDER_ID}' in parents and trashed=false",
            pageSize=10,
            fields="files(id, name, mimeType, createdTime)",
            orderBy="createdTime desc"
        ).execute()
        
        files = results.get('files', [])
        
        if not files:
            print("  📁 폴더가 비어있습니다")
        else:
            print(f"  📁 {len(files)}개 항목 발견:\n")
            for f in files:
                mime = f.get('mimeType', '')
                icon = get_icon(mime)
                print(f"    {icon} {f['name']}")
                print(f"       ID: {f['id']}")
                print(f"       Type: {mime}")
                print()
    except Exception as e:
        print(f"  ❌ 파일 목록 조회 실패: {e}")
        return
    
    # 5. 안건지/속기록 찾기
    print("\n[5] '안건' 또는 '속기' 포함 문서 검색")
    try:
        results = service.files().list(
            q=f"'{FOLDER_ID}' in parents and trashed=false and (name contains '안건' or name contains '속기' or name contains '결과')",
            pageSize=20,
            fields="files(id, name, mimeType)",
        ).execute()
        
        files = results.get('files', [])
        
        if not files:
            print("  🔍 직접적인 안건/속기 문서 없음 - 하위 폴더 탐색 필요")
        else:
            print(f"\n  📄 {len(files)}개 관련 문서 발견:\n")
            for f in files:
                mime = f.get('mimeType', '')
                icon = get_icon(mime)
                print(f"    {icon} {f['name']}")
                print(f"       ID: {f['id']}")
    except Exception as e:
        print(f"  ❌ 검색 실패: {e}")
    
    print("\n" + "=" * 60)
    print("✅ 테스트 완료!")
    print("=" * 60)

def get_icon(mime_type: str) -> str:
    """MIME 타입에 따른 아이콘"""
    if 'folder' in mime_type:
        return '📁'
    elif 'document' in mime_type or 'google-apps.document' in mime_type:
        return '📝'
    elif 'spreadsheet' in mime_type:
        return '📊'
    elif 'pdf' in mime_type:
        return '📕'
    elif 'word' in mime_type:
        return '📘'
    else:
        return '📄'

if __name__ == "__main__":
    main()
