"""Step 2: Classification - Classify and standardize document metadata.

This module handles document classification using:
1. Regex-based pattern matching for initial classification
2. Gemini 2.0 Flash for filename standardization and detailed classification
3. Folder path inference for improved accuracy
"""

import re
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

import google.generativeai as genai
import structlog

from app.core.config import settings
from app.models.document import DocumentCategory, DocumentType, MeetingSubtype

logger = structlog.get_logger()

# Configure Gemini
genai.configure(api_key=settings.GEMINI_API_KEY)


class FileExtensionType(str, Enum):
    """File extension categories for classification."""
    
    MEETING_CAPABLE = "meeting_capable"  # .gdocs, .pdf, .hwp, .docx
    WORK_DOCUMENT = "work_document"  # .gsheet, .pptx, .xlsx
    OTHER = "other"


# Regex patterns for meeting document detection
MEETING_KEYWORDS = [
    r"안건[지]?",
    r"속기[록]?",
    r"결과[지]?",
    r"회의",
    r"운영위",
    r"국장단",
    r"집행위",
    r"학생총회",
]

# Subtype keyword patterns
SUBTYPE_PATTERNS = {
    MeetingSubtype.AGENDA: [r"안건[지]?", r"agenda"],
    MeetingSubtype.MINUTES: [r"속기[록]?", r"minutes", r"회의록"],
    MeetingSubtype.RESULT: [r"결과[지]?", r"result", r"확정"],
}

# File extensions mapping
EXTENSION_MAPPING = {
    ".gdoc": (DocumentType.GOOGLE_DOC, FileExtensionType.MEETING_CAPABLE),
    ".docx": (DocumentType.DOCX, FileExtensionType.MEETING_CAPABLE),
    ".pdf": (DocumentType.PDF, FileExtensionType.MEETING_CAPABLE),
    ".hwp": (DocumentType.HWP, FileExtensionType.MEETING_CAPABLE),
    ".gsheet": (DocumentType.GOOGLE_SHEET, FileExtensionType.WORK_DOCUMENT),
    ".xlsx": (DocumentType.XLSX, FileExtensionType.WORK_DOCUMENT),
    ".pptx": (DocumentType.PPTX, FileExtensionType.WORK_DOCUMENT),
    ".gform": (DocumentType.GOOGLE_FORM, FileExtensionType.OTHER),
}

# LLM Prompt for filename standardization
STANDARDIZATION_PROMPT = """당신은 서울대학교 컴퓨터공학부 학생회 문서 관리 전문가입니다.
아래 파일명을 분석해서 표준 형식으로 바꿔주세요.

## 규칙:
1. '학생회' 뒤에는 반드시 '집행위원회'를 붙일 것
2. 차수 앞에는 '제'를 붙일 것 (예: 1차 → 제1차)
3. 모든 파일명은 '[문서종류] 소속 세부소속 차수 회의' 형식으로 통일할 것
4. 문서종류는 [안건지], [속기록], [결과지] 중 하나
5. 연도가 있으면 맨 앞에 붙일 것 (예: 2024년)

## 예시:
입력: "제38대 학생회 국장단 1차 회의 속기록"
출력: "[속기록] 제38대 학생회 집행위원회 국장단 제1차 회의"

입력: "운영위 5차 결과"
출력: "[결과지] 운영위원회 제5차 회의"

## 분석할 파일:
파일명: {filename}
폴더 경로: {folder_path}

## 응답 형식 (JSON):
{{
    "standardized_name": "표준화된 파일명",
    "year": 연도 (숫자, 없으면 null),
    "organization": "소속 (예: 집행위원회, 운영위원회)",
    "sub_organization": "세부소속 (예: 국장단, 문화국)",
    "meeting_number": 회의 차수 (숫자, 없으면 null),
    "document_type": "안건지/속기록/결과지/기타",
    "is_meeting_document": true/false,
    "confidence": 0.0-1.0
}}

JSON만 출력하세요. 다른 설명은 붙이지 마세요."""

# LLM Prompt for document classification
CLASSIFICATION_PROMPT = """당신은 서울대학교 컴퓨터공학부 학생회 문서 분류 전문가입니다.
주어진 파일 정보를 분석하여 분류해주세요.

## 분류 체계:
1. **회의 서류** (meeting_document): 안건지, 속기록, 결과지 등 회의 관련 문서
   - 보통 .docx, .pdf, .hwp 형식
   - 파일명에 '회의', '안건', '속기', '결과', '운영위', '국장단' 등 포함
   
2. **업무 서류** (work_document): 실제 업무용 문서
   - .xlsx, .pptx, .gsheet 등
   - 예산안, 기획안, 프레젠테이션 등
   
3. **기타 파일** (other_document): 위에 해당하지 않는 문서

## 분석할 파일:
파일명: {filename}
확장자: {extension}
폴더 경로: {folder_path}

## 응답 형식 (JSON):
{{
    "category": "meeting_document/work_document/other_document",
    "meeting_subtype": "agenda/minutes/result/null",
    "department": "담당 국서 (예: 문화국, 복지국, null)",
    "event_name": "관련 행사명 (추정, 없으면 null)",
    "year": 연도 (숫자, 없으면 null),
    "confidence": 0.0-1.0
}}

JSON만 출력하세요."""


@dataclass
class ClassificationResult:
    """Result of document classification."""
    
    doc_type: DocumentType
    doc_category: DocumentCategory
    meeting_subtype: MeetingSubtype | None
    standardized_name: str | None
    department: str | None
    event_name: str | None
    year: int | None
    confidence: float
    raw_llm_response: dict | None = None


class ClassificationService:
    """
    Service for classifying documents based on filename and folder path.

    Uses a two-stage approach:
    1. Regex-based quick classification for obvious patterns
    2. LLM-based classification for complex cases and standardization
    """

    def __init__(self):
        """Initialize classification service with Gemini 2.0 Flash."""
        self.model = genai.GenerativeModel(settings.GEMINI_MODEL)

    def _extract_year_from_path(self, filename: str, folder_path: str) -> int | None:
        """
        Extract year from filename or folder path using regex.

        Handles patterns like:
        - 2025_회의록, 2024년, 2025.05.01
        - /문서/2024/회의록/

        Args:
            filename: Document filename
            folder_path: Full folder path

        Returns:
            Year as integer if found, None otherwise
        """
        combined = f"{folder_path}/{filename}"

        # Pattern 1: 4-digit year (2020-2029)
        match = re.search(r'20[2][0-9]', combined)
        if match:
            return int(match.group())

        # Pattern 2: 2-digit year with context (예: '25년, 24학년도)
        match = re.search(r'[\'"]?(2[4-9])(?:년|학년)', combined)
        if match:
            return 2000 + int(match.group(1))

        return None

    def _get_file_extension_type(self, extension: str) -> tuple[DocumentType, FileExtensionType]:
        """Get document type and extension category from file extension."""
        ext = extension.lower()
        if ext in EXTENSION_MAPPING:
            return EXTENSION_MAPPING[ext]
        return DocumentType.OTHER, FileExtensionType.OTHER

    def _regex_classify_meeting_subtype(self, filename: str) -> MeetingSubtype | None:
        """
        Quick regex-based classification for meeting document subtypes.
        
        Args:
            filename: The filename to classify
            
        Returns:
            MeetingSubtype if detected, None otherwise
        """
        filename_lower = filename.lower()
        
        for subtype, patterns in SUBTYPE_PATTERNS.items():
            for pattern in patterns:
                if re.search(pattern, filename_lower, re.IGNORECASE):
                    return subtype
        
        return None

    def _is_meeting_document(self, filename: str) -> bool:
        """Check if filename contains meeting-related keywords."""
        filename_lower = filename.lower()
        return any(
            re.search(pattern, filename_lower, re.IGNORECASE)
            for pattern in MEETING_KEYWORDS
        )

    async def classify_document(
        self,
        filename: str,
        folder_path: str,
        extension: str | None = None,
        use_llm: bool = True,
    ) -> ClassificationResult:
        """
        Classify a document based on filename and folder path.
        
        Args:
            filename: The document filename
            folder_path: Full folder path for context
            extension: File extension (extracted from filename if not provided)
            use_llm: Whether to use LLM for enhanced classification
            
        Returns:
            ClassificationResult with all classification data
        """
        # Extract extension if not provided
        if not extension:
            extension = Path(filename).suffix
        
        # Stage 1: Extension-based classification
        doc_type, ext_type = self._get_file_extension_type(extension)
        
        # Stage 2: Pattern-based classification
        is_meeting = self._is_meeting_document(filename)
        meeting_subtype = self._regex_classify_meeting_subtype(filename)
        
        # Determine initial category
        if ext_type == FileExtensionType.MEETING_CAPABLE and is_meeting:
            doc_category = DocumentCategory.MEETING_DOCUMENT
        elif ext_type == FileExtensionType.WORK_DOCUMENT:
            doc_category = DocumentCategory.WORK_DOCUMENT
        elif ext_type == FileExtensionType.MEETING_CAPABLE and not is_meeting:
            doc_category = DocumentCategory.OTHER_DOCUMENT
        else:
            doc_category = DocumentCategory.OTHER_DOCUMENT

        standardized_name = None
        department = None
        event_name = None
        confidence = 0.7  # Base confidence for regex classification
        llm_response = None

        # Stage 3: Regex-based year extraction (fast, free)
        year = self._extract_year_from_path(filename, folder_path)
        if year:
            logger.debug("Year extracted via regex", year=year, filename=filename)

        # Stage 4: LLM enhancement (for meeting docs OR when year not found)
        needs_llm = doc_category == DocumentCategory.MEETING_DOCUMENT or year is None
        if use_llm and needs_llm:
            try:
                llm_result = await self._llm_classify_and_standardize(
                    filename, folder_path, extension
                )
                if llm_result:
                    standardized_name = llm_result.get("standardized_name")
                    department = llm_result.get("department")
                    event_name = llm_result.get("event_name")
                    # Only use LLM year if regex didn't find one
                    if year is None:
                        year = llm_result.get("year")
                    confidence = llm_result.get("confidence", 0.85)
                    llm_response = llm_result
                    
                    # Update meeting subtype from LLM if not detected by regex
                    if not meeting_subtype:
                        llm_doc_type = llm_result.get("document_type", "").lower()
                        if "안건" in llm_doc_type or llm_doc_type == "agenda":
                            meeting_subtype = MeetingSubtype.AGENDA
                        elif "속기" in llm_doc_type or llm_doc_type == "minutes":
                            meeting_subtype = MeetingSubtype.MINUTES
                        elif "결과" in llm_doc_type or llm_doc_type == "result":
                            meeting_subtype = MeetingSubtype.RESULT
                            
            except Exception as e:
                logger.warning("LLM classification failed", error=str(e))
                confidence = 0.6

        return ClassificationResult(
            doc_type=doc_type,
            doc_category=doc_category,
            meeting_subtype=meeting_subtype,
            standardized_name=standardized_name,
            department=department,
            event_name=event_name,
            year=year,
            confidence=confidence,
            raw_llm_response=llm_response,
        )

    async def _llm_classify_and_standardize(
        self,
        filename: str,
        folder_path: str,
        extension: str,
    ) -> dict[str, Any] | None:
        """
        Use Gemini 2.0 Flash for filename standardization and classification.
        
        Args:
            filename: Original filename
            folder_path: Full folder path for context
            extension: File extension
            
        Returns:
            Dictionary with standardized name and classification data
        """
        import json
        
        # First, get standardized name
        prompt = STANDARDIZATION_PROMPT.format(
            filename=filename,
            folder_path=folder_path,
        )
        
        try:
            response = await self.model.generate_content_async(prompt)
            result_text = response.text.strip()
            
            # Clean up response (remove markdown code blocks if present)
            if result_text.startswith("```"):
                result_text = result_text.split("```")[1]
                if result_text.startswith("json"):
                    result_text = result_text[4:]
            
            result = json.loads(result_text)
            
            # Perform additional classification for more details
            class_prompt = CLASSIFICATION_PROMPT.format(
                filename=filename,
                extension=extension,
                folder_path=folder_path,
            )
            
            class_response = await self.model.generate_content_async(class_prompt)
            class_text = class_response.text.strip()
            
            if class_text.startswith("```"):
                class_text = class_text.split("```")[1]
                if class_text.startswith("json"):
                    class_text = class_text[4:]
            
            class_result = json.loads(class_text)
            
            # Merge results
            result.update({
                "department": class_result.get("department"),
                "event_name": class_result.get("event_name"),
            })
            
            return result
            
        except Exception as e:
            logger.error("LLM parsing failed", error=str(e))
            return None

    async def batch_classify(
        self,
        files: list[dict[str, str]],
        use_llm: bool = True,
    ) -> list[ClassificationResult]:
        """
        Classify multiple files in batch.
        
        Args:
            files: List of dicts with 'name', 'path', 'extension' keys
            use_llm: Whether to use LLM for enhanced classification
            
        Returns:
            List of ClassificationResult objects
        """
        import asyncio
        
        tasks = [
            self.classify_document(
                filename=f["name"],
                folder_path=f.get("path", f.get("full_folder_path", "")),
                extension=f.get("extension"),
                use_llm=use_llm,
            )
            for f in files
        ]
        
        return await asyncio.gather(*tasks)
