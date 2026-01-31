"""Unit tests for classification logic (Step 2)."""

import pytest

from app.models.document import DocumentCategory, DocumentType, MeetingSubtype
from app.pipeline.step_02_classify import ClassificationService


@pytest.fixture
def classifier():
    """Create classification service instance."""
    return ClassificationService()


class TestRegexClassification:
    """Tests for regex-based classification (no LLM)."""

    @pytest.mark.asyncio
    async def test_meeting_agenda_classification(self, classifier):
        """Test classification of 안건지 document."""
        result = await classifier.classify_document(
            filename="제38대 학생회 국장단 1차 회의 안건지.docx",
            folder_path="/회의자료/국장단회의/",
            use_llm=False,
        )
        
        assert result.doc_category == DocumentCategory.MEETING_DOCUMENT
        assert result.meeting_subtype == MeetingSubtype.AGENDA
        assert result.doc_type == DocumentType.DOCX

    @pytest.mark.asyncio
    async def test_meeting_minutes_classification(self, classifier):
        """Test classification of 속기록 document."""
        result = await classifier.classify_document(
            filename="운영위 5차 속기록.pdf",
            folder_path="/회의자료/운영위/",
            use_llm=False,
        )
        
        assert result.doc_category == DocumentCategory.MEETING_DOCUMENT
        assert result.meeting_subtype == MeetingSubtype.MINUTES
        assert result.doc_type == DocumentType.PDF

    @pytest.mark.asyncio
    async def test_meeting_result_classification(self, classifier):
        """Test classification of 결과지 document."""
        result = await classifier.classify_document(
            filename="집행위 3차 결과지.hwp",
            folder_path="/회의자료/집행위/",
            use_llm=False,
        )
        
        assert result.doc_category == DocumentCategory.MEETING_DOCUMENT
        assert result.meeting_subtype == MeetingSubtype.RESULT
        assert result.doc_type == DocumentType.HWP

    @pytest.mark.asyncio
    async def test_work_document_classification(self, classifier):
        """Test classification of work document (sheet)."""
        result = await classifier.classify_document(
            filename="축제 예산안.xlsx",
            folder_path="/업무자료/",
            use_llm=False,
        )
        
        assert result.doc_category == DocumentCategory.WORK_DOCUMENT
        assert result.meeting_subtype is None
        assert result.doc_type == DocumentType.XLSX

    @pytest.mark.asyncio
    async def test_non_meeting_doc_classification(self, classifier):
        """Test classification of non-meeting doc format."""
        result = await classifier.classify_document(
            filename="학생회 소개.docx",
            folder_path="/홍보자료/",
            use_llm=False,
        )
        
        # docx but no meeting keywords -> OTHER
        assert result.doc_category == DocumentCategory.OTHER_DOCUMENT
        assert result.meeting_subtype is None


class TestDocumentReliability:
    """Tests for document reliability scoring."""

    def test_result_highest_reliability(self):
        """결과지 should have highest reliability score."""
        from app.models.document import Document, MeetingSubtype
        
        doc = Document(
            drive_id="test",
            drive_name="test.docx",
            meeting_subtype=MeetingSubtype.RESULT,
        )
        assert doc.reliability_score == 3  # Highest

    def test_minutes_medium_reliability(self):
        """속기록 should have medium reliability score."""
        from app.models.document import Document, MeetingSubtype
        
        doc = Document(
            drive_id="test",
            drive_name="test.docx",
            meeting_subtype=MeetingSubtype.MINUTES,
        )
        assert doc.reliability_score == 2  # Medium

    def test_agenda_low_reliability(self):
        """안건지 should have low reliability score."""
        from app.models.document import Document, MeetingSubtype
        
        doc = Document(
            drive_id="test",
            drive_name="test.docx",
            meeting_subtype=MeetingSubtype.AGENDA,
        )
        assert doc.reliability_score == 1  # Low

    def test_non_meeting_no_reliability(self):
        """Non-meeting documents should have 0 reliability."""
        from app.models.document import Document
        
        doc = Document(
            drive_id="test",
            drive_name="test.docx",
            meeting_subtype=None,
        )
        assert doc.reliability_score == 0


class TestAccessLevel:
    """Tests for access level (permission) system."""

    @pytest.mark.asyncio
    async def test_result_public_access(self):
        """결과지 should default to public access."""
        from app.pipeline.step_06_enrich import MetadataEnrichmentService
        from app.models.document import Document, DocumentCategory, MeetingSubtype
        
        doc = Document(
            drive_id="test",
            drive_name="test.docx",
            doc_category=DocumentCategory.MEETING_DOCUMENT,
            meeting_subtype=MeetingSubtype.RESULT,
        )
        
        # Access level determination (without full DB)
        enricher = MetadataEnrichmentService.__new__(MetadataEnrichmentService)
        access_level = enricher._determine_access_level(doc, {})
        
        assert access_level == 4  # Public

    @pytest.mark.asyncio
    async def test_minutes_council_access(self):
        """속기록 should have council-only access."""
        from app.pipeline.step_06_enrich import MetadataEnrichmentService
        from app.models.document import Document, DocumentCategory, MeetingSubtype
        
        doc = Document(
            drive_id="test",
            drive_name="test.docx",
            doc_category=DocumentCategory.MEETING_DOCUMENT,
            meeting_subtype=MeetingSubtype.MINUTES,
        )
        
        enricher = MetadataEnrichmentService.__new__(MetadataEnrichmentService)
        access_level = enricher._determine_access_level(doc, {})
        
        assert access_level == 3  # Council members
