from google.oauth2 import service_account
from googleapiclient.discovery import build
import os

SCOPES = [
    'https://www.googleapis.com/auth/drive',
    'https://www.googleapis.com/auth/documents'
]
CREDENTIALS_PATH = '/app/credentials/google_key.json'

print('=' * 60)
print('서비스 계정 Drive 용량 및 파일 확인')
print('=' * 60)

# Auth
credentials = service_account.Credentials.from_service_account_file(CREDENTIALS_PATH, scopes=SCOPES)
drive_service = build('drive', 'v3', credentials=credentials)

# 1. 용량 확인
print('\n[1] Drive 용량 정보')
try:
    about = drive_service.about().get(fields='storageQuota, user').execute()
    quota = about.get('storageQuota', {})
    user = about.get('user', {})
    
    limit = int(quota.get('limit', 0))
    usage = int(quota.get('usage', 0))
    
    print(f"  계정: {user.get('emailAddress')}")
    print(f"  총 용량: {limit / (1024**3):.2f} GB")
    print(f"  사용 중: {usage / (1024**3):.2f} GB")
    print(f"  사용률: {usage/limit*100:.1f}%" if limit > 0 else "  무제한")
except Exception as e:
    print(f"  Error: {e}")

# 2. 파일 목록
print('\n[2] 서비스 계정이 소유한 파일들')
try:
    results = drive_service.files().list(
        q="'me' in owners",
        pageSize=30,
        fields='files(id, name, mimeType, size, createdTime)',
        orderBy='createdTime desc'
    ).execute()
    
    files = results.get('files', [])
    print(f"  총 {len(files)}개 파일 발견:\n")
    
    total_size = 0
    for f in files:
        name = f['name'][:40]
        size = int(f.get('size', 0))
        total_size += size
        size_str = f"{size/1024:.1f}KB" if size > 0 else "N/A"
        print(f"  - {name} ({size_str})")
        print(f"    ID: {f['id']}")
    
    print(f"\n  소유 파일 총 크기: {total_size / (1024**2):.2f} MB")
except Exception as e:
    print(f"  Error: {e}")
