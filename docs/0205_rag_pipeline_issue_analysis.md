# RAG 파이프라인 이슈 분석 및 해결 과제

> **작성일**: 2026-02-05  
> **담당**: 팀원 (RAG 파이프라인 담당)  
> **상태**: 🔴 Critical Issues

---

## 문제 0: `parsed_content` 길이 0 버그 ⚠️ FIXED

### 증상
- DB에 저장된 `parsed_content` 길이가 0
- 그러나 `preprocessed_content`는 3,000자 내외로 정상

### 근본 원인 (확인됨)
```python
# pipeline.py line 214 (수정 전)
document.parsed_content = parse_result.html_content  # ❌ 빈 문자열!
```

Upstage API 응답:
```json
{"content":{"html":"","markdown":"# 서울대학교..."}}
```
- `html_content`는 **빈 문자열**
- `markdown_content`에 실제 파싱 결과 포함

### 해결 (완료)
```diff
- document.parsed_content = parse_result.html_content
+ document.parsed_content = parse_result.markdown_content  # FIXED!
```

📍 **파일**: [app/tasks/pipeline.py](file:///c:/Users/imtae/madcamp/2025Winter_4th/backend/app/tasks/pipeline.py) line 225

---

## 문제 1: 8개 업로드 → 59개 문서 생성

### 증상
- 폴더에 8개 파일만 업로드
- DB에는 59개 문서 등록

### 추정 원인
1. **rclone 캐시**: `/app/data/raw` 폴더에 이전 sync 파일이 남아있음
2. **Docker 볼륨**: `docker-compose down -v` 없이 재빌드하면 볼륨 유지됨
3. **재귀 탐색**: [list_synced_files()](file:///c:/Users/imtae/madcamp/2025Winter_4th/backend/app/pipeline/step_01_ingest.py#261-296)가 `rglob("*")`로 모든 하위 폴더 탐색

### 확인 방법
```bash
# 서버에서 실제 파일 수 확인
docker exec council-ai-celery find /app/data/raw -type f | wc -l

# 파일 목록 확인
docker exec council-ai-celery ls -laR /app/data/raw
```

### 해결 방향
1. **볼륨 완전 삭제 후 재빌드**:
```bash
docker-compose down -v  # 볼륨까지 삭제
rm -rf data/raw/*       # 로컬 데이터도 삭제
docker-compose up -d --build
```

2. **Ingestion 전 폴더 클린업 로직 추가** (선택):
```python
# step_01_ingest.py run_step1()에 추가
if cleanup_before_sync:
    shutil.rmtree(self.work_dir, ignore_errors=True)
    self.work_dir.mkdir(parents=True, exist_ok=True)
```

---

## 문제 2: 59 문서에 4개 이벤트만 생성

### 증상
- 59개 문서, 805개 청크 생성
- 그러나 이벤트는 **4개**만 생성됨
- 인수인계서는 행사 기반 → 행사가 너무 적으면 품질 저하

### 확인 SQL
```sql
-- 현재 이벤트 목록
SELECT id, title, year, department, event_scope 
FROM events 
ORDER BY id;

-- 문서별 이벤트 매핑 현황
SELECT d.id, d.drive_name, e.title as event_title
FROM documents d
LEFT JOIN events e ON d.event_id = e.id
LIMIT 20;

-- 이벤트 없는 문서 수
SELECT COUNT(*) 
FROM documents 
WHERE event_id IS NULL;
```

### 추정 원인
[step_06_enrich.py](file:///c:/Users/imtae/madcamp/2025Winter_4th/backend/app/pipeline/step_06_enrich.py)의 이벤트 생성 로직 분석 필요:
- 이벤트 추론이 너무 보수적 (LLM이 "모르겠음" 반환)
- 이벤트 중복 감지가 너무 공격적 (비슷하면 같은 이벤트로 묶음)
- 회의록 외 문서는 이벤트 생성 안 함

### 해결 방향
1. **Step 6 Enrichment 로그 강화**:
   - 이벤트 생성/매칭 시 상세 로그 추가
   - LLM 응답 원문 로깅

2. **이벤트 생성 조건 완화**:
   - 문서 분류 기반 자동 이벤트 생성
   - "집행위원회", "총회" 등 키워드 기반 생성

---

## 검증용 SQL 모음

```sql
-- 전체 현황
SELECT 'documents' as tbl, COUNT(*) FROM documents
UNION ALL SELECT 'chunks', COUNT(*) FROM document_chunks
UNION ALL SELECT 'events', COUNT(*) FROM events;

-- 이벤트별 문서 수
SELECT e.id, e.title, COUNT(d.id) as doc_count
FROM events e
LEFT JOIN documents d ON e.id = d.event_id
GROUP BY e.id, e.title;

-- 문서 상태별 집계
SELECT status, COUNT(*) 
FROM documents 
GROUP BY status;

-- parsed_content 길이 확인 (버그 수정 검증)
SELECT id, drive_name, 
       LENGTH(parsed_content) as parsed_len,
       LENGTH(preprocessed_content) as preprocessed_len
FROM documents
ORDER BY id DESC
LIMIT 10;
```

---

## 우선순위

| # | 문제 | 심각도 | 상태 |
|---|------|--------|------|
| 0 | parsed_content 저장 버그 | 🔴 Critical | ✅ Fixed |
| 1 | 문서 수 불일치 | 🟡 High | 📋 Investigation |
| 2 | 이벤트 생성 부족 | 🟡 High | 📋 Analysis Needed |

---

## 재배포 후 테스트 체크리스트

- [ ] DB 완전 초기화 (`docker-compose down -v`)
- [ ] `/app/data/raw` 폴더 비우기
- [ ] 8개 파일만 있는 폴더로 Ingestion 테스트
- [ ] `parsed_content` 길이 > 0 확인
- [ ] 문서 수 = 8개 확인
- [ ] 이벤트 생성 로그 분석
