import os
import requests
from dotenv import load_dotenv

load_dotenv()

api_key = os.getenv("UPSTAGE_API_KEY")
url = "https://api.upstage.ai/v1/document-ai/layout-analysis"
file_path = "data/raw/1차 회의/[안건지] 제37대 서울대학교 공과대학 컴퓨터공학부 학생회 [FLOW] 제1차 집행위원회 국장단회의 안건지.pdf"

if not os.path.exists(file_path):
    print(f"❌ 파일을 찾을 수 없습니다: {file_path}")
    exit(1)

print(f"🚀 Upstage API 테스트 시작: {file_path}")
headers = {"Authorization": f"Bearer {api_key}"}
files = {"document": open(file_path, "rb")}

try:
    response = requests.post(url, headers=headers, files=files)
    response.raise_for_status()
    result = response.json()
    
    # 결과 분석
    print("\n✅ API 호출 성공!")
    print(f"Status Code: {response.status_code}")
    
    # 응답 키 확인
    print(f"Response Keys: {list(result.keys())}")
    
    markdown = result.get("markdown", "")
    if not markdown and "content" in result:
        markdown = result["content"].get("markdown", "")
        
    print(f"\n📝 추출된 마크다운 길이: {len(markdown)} 자")
    print("-" * 50)
    print(markdown[:500])  # 앞부분 500자만 출력
    print("-" * 50)

except Exception as e:
    print(f"\n❌ 에러 발생: {e}")
    if 'response' in locals():
        print(f"응답 내용: {response.text}")

