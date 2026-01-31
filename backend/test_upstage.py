import os
import requests
import json

# 환경 변수 로드 (컨테이너 안에서는 이미 로드되어 있을 수 있지만 안전하게)
api_key = os.environ.get("UPSTAGE_API_KEY")
if not api_key:
    # .env 파일 수동 로드 시도
    from dotenv import load_dotenv
    load_dotenv()
    api_key = os.getenv("UPSTAGE_API_KEY")

url = "https://api.upstage.ai/v1/document-ai/layout-analysis"
# 컨테이너 내부 기준 경로
file_path = "/app/data/raw/1차 회의/[안건지] 제37대 서울대학교 공과대학 컴퓨터공학부 학생회 [FLOW] 제1차 집행위원회 국장단회의 안건지.pdf"

print(f"🚀 [테스트 시작] 파일 경로: {file_path}")

if not os.path.exists(file_path):
    print(f"❌ 파일을 찾을 수 없습니다. 경로를 확인하세요.")
    # 디버깅: 현재 폴더 구조 출력
    print(f"현재 위치: {os.getcwd()}")
    print(f"data/raw 목록: {os.listdir('/app/data/raw')}")
    exit(1)

headers = {"Authorization": f"Bearer {api_key}"}

try:
    with open(file_path, "rb") as f:
        files = {"document": f}
        print("📡 Upstage API 요청 전송 중...")
        response = requests.post(url, headers=headers, files=files)
        
    print(f"📡 응답 상태 코드: {response.status_code}")
    
    if response.status_code != 200:
        print(f"❌ API 에러 발생: {response.text}")
        exit(1)
        
    result = response.json()
    print("✅ API 호출 성공!")
    
    # 응답 키 확인 (디버깅의 핵심)
    print(f"🔑 응답 최상위 키: {list(result.keys())}")
    
    # 내용 추출 시도 (구조가 다를 수 있으므로 여러 경로 확인)
    content = ""
    if "content" in result and isinstance(result["content"], dict):
        content = result["content"].get("markdown", "")
        html = result["content"].get("html", "")
        print(f"📄 HTML 데이터 유무: {'있음' if html else '없음'}")
    elif "markdown" in result:
        content = result["markdown"]
    else:
        print("⚠️ 'markdown' 또는 'content.markdown' 키를 찾을 수 없습니다.")
        print(f"전체 응답 구조: {json.dumps(result, indent=2, ensure_ascii=False)[:500]}...")

    print("-" * 50)
    print(f"📝 추출된 마크다운 길이: {len(content)} 자")
    
    if len(content) > 0:
        print(f"🔍 본문 미리보기 (첫 200자):\n{content[:200]}")
    else:
        print("❌ 본문 길이가 0입니다. (빈 응답)")
        
    print("-" * 50)

except Exception as e:
    print(f"\n❌ 실행 중 치명적 에러 발생: {e}")
