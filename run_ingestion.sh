#!/bin/bash

# 1. API Endpoint 설정
API_URL="http://localhost:8000/api/v1/rag/hybrid-ingest"
API_KEY="dev-key"

echo "🚀 [$(date)] 데이터 수집 및 Upstage 파싱 파이프라인 시작..."

# 2. API 호출
response=$(curl -s -w "\n%{http_code}" -X POST "$API_URL" \
    -H "X-API-Key: $API_KEY" \
    -H "Content-Type: application/json" \
    -d '{"limit": 20}')

# 3. 응답 결과 분석
body=$(echo "$response" | sed '$d')
status_code=$(echo "$response" | tail -n1)

if [ "$status_code" -eq 200 ]; then
    echo "✅ 성공: 파이프라인이 정상적으로 시작되었습니다."
    echo "📩 응답 내용: $body"
else
    echo "❌ 실패: 에러 발생 (Status Code: $status_code)"
    echo "📩 에러 내용: $body"
fi

echo "📂 data/raw 와 data/processed 폴더를 확인하세요."
