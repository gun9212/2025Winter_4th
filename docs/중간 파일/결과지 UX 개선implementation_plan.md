# Smart Minutes UX Improvement & On-Demand RAG

## 문제 분석

### Issue 1: UX Inconsistency
- 안건지: Picker 방식 ✅
- 속기록: Selectbox 방식 (Untitled 무의미) ❌
- **해결**: Picker 방식으로 통일

### Issue 2: Untitled 버그
- [step_01_ingest.py](file:///c:/Users/imtae/madcamp/2025Winter_4th/backend/app/pipeline/step_01_ingest.py)의 [_fetch_drive_metadata()](file:///c:/Users/imtae/madcamp/2025Winter_4th/backend/app/pipeline/step_01_ingest.py#159-236)가 rclone lsjson 사용
- rclone은 [Name](file:///c:/Users/imtae/madcamp/2025Winter_4th/frontend/src/Code.gs#134-142) 필드를 반환하지만, Google Drive native ID 조회시 정상 작동
- **근본 원인**: DB 저장 시 `drive_name`이 local file 이름이 아닌 빈 값으로 저장

![현재 Untitled 문제](file:///C:/Users/imtae/.gemini/antigravity/brain/99e38b4f-a3a8-434f-ab63-73db55a1f452/uploaded_media_1770274854358.png)

### Issue 3: Flow Gap
- Picker로 선택한 파일이 RAG 학습 안 되어 있으면 404 에러
- **해결**: On-demand ingestion 자동 실행

---

## Proposed Changes

### Task A: Frontend UX Reversion (Picker)

#### [MODIFY] [Sidebar.html](file:///c:/Users/imtae/madcamp/2025Winter_4th/frontend/src/Sidebar.html)
- RAG Selectbox 제거
- Picker 버튼 복원 (안건지와 동일 스타일)

```html
<!-- 속기록 선택 (Picker 방식) -->
<div class="mb-4">
  <label class="block text-xs text-google-gray mb-1">속기록 문서 (필수) *</label>
  <div class="flex gap-2">
    <input type="text" id="transcript-doc-id" class="flex-1 border rounded px-3 py-2 text-sm bg-gray-50"
           placeholder="속기록 ID" readonly>
    <button type="button" class="picker-btn" data-target="transcript-doc-id" data-type="doc">
      📄 선택
    </button>
  </div>
  <p id="transcript-doc-name" class="text-xs text-gray-500 mt-1 truncate"></p>
</div>
```

#### [MODIFY] [Utils.gs](file:///c:/Users/imtae/madcamp/2025Winter_4th/frontend/src/Utils.gs)
- [apiGenerateMinutes()](file:///c:/Users/imtae/madcamp/2025Winter_4th/frontend/src/Utils.gs#222-290) payload에 `transcript_doc_id` 전송
- Backend가 Drive ID를 받아 처리

```javascript
// v2.1: transcript_doc_id (Drive ID) 전송
const payload = {
  agenda_doc_id: data.agendaDocId,
  transcript_doc_id: data.transcriptDocId,  // Drive ID (Picker)
  meeting_name: data.meetingName,
  // ...
};
```

---

### Task B: Backend On-Demand Ingestion

#### [MODIFY] [features_dto.py](file:///c:/Users/imtae/madcamp/2025Winter_4th/backend/app/schemas/features_dto.py)
- `source_document_id` 제거 → `transcript_doc_id` 활용
- 타입: [str](file:///c:/Users/imtae/madcamp/2025Winter_4th/backend/tests/unit/test_text_utils.py#389-398) (Google Drive ID)

```python
class MinutesGenerationRequest(BaseModel):
    agenda_doc_id: str = Field(...)  # Google Docs ID
    transcript_doc_id: str = Field(...)  # Google Drive ID (Picker)
    # source_document_id: int - REMOVED
```

#### [MODIFY] [features.py](file:///c:/Users/imtae/madcamp/2025Winter_4th/backend/app/tasks/features.py)
- Phase 0에 On-demand RAG 로직 추가

```python
# Phase 0: On-demand RAG Ingestion
async def _ensure_rag_ready(drive_id: str) -> Document:
    """Ensure document is RAG-processed, ingest on-demand if needed."""
    async with async_session_factory() as db:
        # 1. DB에서 Drive ID로 조회
        result = await db.execute(
            select(Document).where(Document.drive_id == drive_id)
        )
        doc = result.scalar_one_or_none()
        
        if doc and doc.status == DocumentStatus.COMPLETED:
            return doc  # Case 1: Already processed
        
        if not doc:
            # Case 2: Not in DB - On-demand ingest
            logger.info("📚 Document not in DB, starting on-demand ingestion", drive_id=drive_id)
            
            # Fetch metadata from Drive API
            drive_service = GoogleDriveService()
            meta = drive_service.get_file_metadata(drive_id)
            file_name = meta.get("name", "Untitled")
            
            # Create Document in DB
            doc = Document(
                drive_id=drive_id,
                drive_name=file_name,
                mime_type=meta.get("mimeType", ""),
                doc_type=get_document_type(meta.get("mimeType", "")),
                status=DocumentStatus.PENDING,
            )
            db.add(doc)
            await db.commit()
            await db.refresh(doc)
            
            # Trigger RAG pipeline (sync for now)
            from app.tasks.pipeline import process_single_document
            process_single_document.delay(doc.id)
            
            # Wait for completion (polling)
            # ...
            
        return doc
```

---

### Task C: Untitled Bug Fix

#### Root Cause
`scan_local_files()` 메서드가 로컬 파일 시스템의 이름을 사용:
- rclone sync로 다운로드된 파일이 정상 이름 가짐
- 하지만 [_fetch_drive_metadata()](file:///c:/Users/imtae/madcamp/2025Winter_4th/backend/app/pipeline/step_01_ingest.py#159-236) lsjson이 `.gdoc` 확장자 매핑 실패

#### Fix Plan
1. [get_file_metadata()](file:///c:/Users/imtae/madcamp/2025Winter_4th/backend/app/services/google/drive.py#180-198) 호출하여 Google Drive API에서 직접 이름 조회
2. DB 저장 시 [name](file:///c:/Users/imtae/madcamp/2025Winter_4th/backend/app/pipeline/step_01_ingest.py#144-158) 필드 보장

```python
# In register_files_to_db()
if not file_info.get("name") or file_info.get("name") == "Untitled":
    # Fallback: Query Drive API for real name
    try:
        meta = GoogleDriveService().get_file_metadata(drive_id)
        file_name = meta.get("name", file_info.get("name", "Untitled"))
    except:
        file_name = file_info.get("name", "Untitled")
```

---

## Verification Plan

### Automated Tests
```bash
# 기존 단위 테스트 실행
python -m pytest tests/unit/test_text_utils.py -v
```

### Manual Verification
1. Sidebar에서 Picker로 속기록 선택
2. 학습 안 된 문서 선택 시 자동 학습 트리거 확인
3. 결과지 정상 생성 확인
