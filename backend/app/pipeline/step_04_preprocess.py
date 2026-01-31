"""Step 4: Preprocessing - Prepare parsed content for chunking using LLM.

This module handles document preprocessing:
1. LLM-based agenda item structure injection
2. Header normalization (#, ##) for Parent-Child chunking
3. Content cleanup and formatting
"""

from dataclasses import dataclass

import google.generativeai as genai
import structlog

from app.core.config import settings

logger = structlog.get_logger()

# Configure Gemini
genai.configure(api_key=settings.GEMINI_API_KEY)


# LLM Prompt for preprocessing meeting documents
PREPROCESSING_PROMPT = """당신은 서울대학교 컴퓨터공학부 학생회 회의록 전문가입니다.

아래 회의 문서를 분석하여 Markdown 헤더 구조를 추가해주세요.

## 규칙:
1. **안건 종류**는 `#` (H1) 헤더로 표시
   - 예: `# 보고안건`, `# 논의안건`, `# 의결안건`
   
2. **개별 안건**은 `##` (H2) 헤더로 표시
   - 예: `## 1. 축제 가수 섭외 건`, `## 2. 예산안 심의 건`
   
3. 기존 내용은 최대한 유지하면서 헤더만 추가
4. 문서 시작 부분의 안건 요약/목록을 참고하여 본문을 구분
5. 각 안건 내용은 해당 `##` 헤더 아래에 배치

## 출력 형식:
- Markdown 형식으로 출력
- 헤더와 본문만 출력 (설명 없이)
- 원본 내용 유지, 헤더 구조만 추가

## 입력 문서:
{content}

---
위 문서를 Markdown 헤더 구조로 변환하세요."""


# Prompt for non-meeting documents (simpler structure)
SIMPLE_PREPROCESSING_PROMPT = """아래 문서의 내용을 정리하여 Markdown 형식으로 변환해주세요.

## 규칙:
1. 주요 섹션은 `##` 헤더로 표시
2. 기존 구조와 내용 유지
3. 불필요한 공백이나 서식은 정리

## 입력 문서:
{content}

---
Markdown으로 변환된 문서만 출력하세요."""


@dataclass
class PreprocessingResult:
    """Result of document preprocessing."""
    
    processed_content: str
    original_content: str
    headers_found: list[str]
    sections_count: int
    is_meeting_document: bool


class PreprocessingService:
    """
    Service for preprocessing parsed documents before chunking.
    
    Uses Gemini 2.0 Flash to inject proper Markdown header structure
    for Parent-Child chunking strategy.
    
    Meeting documents get special treatment:
        - # for agenda types (보고안건, 논의안건, 의결안건)
        - ## for individual agenda items
    """

    def __init__(self):
        """Initialize preprocessing service."""
        self.model = genai.GenerativeModel(settings.GEMINI_MODEL)

    async def preprocess_document(
        self,
        content: str,
        is_meeting_document: bool = True,
        document_type: str | None = None,
    ) -> PreprocessingResult:
        """
        Preprocess a parsed document for chunking.
        
        Args:
            content: Parsed document content (HTML or text)
            is_meeting_document: Whether this is a meeting document
            document_type: Specific document type (agenda, minutes, result)
            
        Returns:
            PreprocessingResult with structured Markdown content
        """
        # Choose appropriate prompt based on document type
        if is_meeting_document:
            prompt = PREPROCESSING_PROMPT.format(content=content)
        else:
            prompt = SIMPLE_PREPROCESSING_PROMPT.format(content=content)

        try:
            response = await self.model.generate_content_async(prompt)
            processed_content = response.text.strip()
            
            # Clean up any markdown code blocks from LLM response
            if processed_content.startswith("```"):
                lines = processed_content.split("\n")
                # Remove first and last lines if they're code block markers
                if lines[0].startswith("```"):
                    lines = lines[1:]
                if lines and lines[-1].strip() == "```":
                    lines = lines[:-1]
                processed_content = "\n".join(lines)

            # Extract headers for metadata
            headers = self._extract_headers(processed_content)
            sections_count = len([h for h in headers if h.startswith("## ")])

            return PreprocessingResult(
                processed_content=processed_content,
                original_content=content,
                headers_found=headers,
                sections_count=sections_count,
                is_meeting_document=is_meeting_document,
            )

        except Exception as e:
            logger.error("Preprocessing failed", error=str(e))
            # Fall back to original content with basic cleanup
            return PreprocessingResult(
                processed_content=self._basic_cleanup(content),
                original_content=content,
                headers_found=[],
                sections_count=0,
                is_meeting_document=is_meeting_document,
            )

    def _extract_headers(self, content: str) -> list[str]:
        """Extract all Markdown headers from content."""
        import re
        pattern = r'^(#{1,3})\s+(.+)$'
        headers = []
        for match in re.finditer(pattern, content, re.MULTILINE):
            headers.append(f"{match.group(1)} {match.group(2)}")
        return headers

    def _basic_cleanup(self, content: str) -> str:
        """
        Basic cleanup of content without LLM processing.
        
        Removes excessive whitespace and normalizes line breaks.
        """
        import re
        
        # Normalize line breaks
        content = content.replace("\r\n", "\n").replace("\r", "\n")
        
        # Remove excessive blank lines (more than 2 consecutive)
        content = re.sub(r'\n{3,}', '\n\n', content)
        
        # Strip trailing whitespace from lines
        lines = [line.rstrip() for line in content.split('\n')]
        content = '\n'.join(lines)
        
        return content.strip()

    async def extract_agenda_summary(
        self,
        content: str,
    ) -> dict[str, list[str]]:
        """
        Extract agenda summary from meeting document.
        
        Useful for building event timeline data.
        
        Args:
            content: Document content
            
        Returns:
            Dictionary with agenda types as keys and item lists as values
        """
        prompt = """아래 회의 문서에서 안건 목록을 추출해주세요.

## 출력 형식 (JSON):
{
    "보고안건": ["안건1", "안건2"],
    "논의안건": ["안건1", "안건2"],
    "의결안건": ["안건1", "안건2"]
}

없는 종류는 빈 배열로 표시하세요.

## 문서:
{content}

JSON만 출력하세요.""".format(content=content[:5000])  # Limit content length

        try:
            import json
            response = await self.model.generate_content_async(prompt)
            result_text = response.text.strip()
            
            # Clean up JSON response
            if result_text.startswith("```"):
                result_text = result_text.split("```")[1]
                if result_text.startswith("json"):
                    result_text = result_text[4:]
            
            return json.loads(result_text)
            
        except Exception as e:
            logger.warning("Agenda extraction failed", error=str(e))
            return {"보고안건": [], "논의안건": [], "의결안건": []}

    async def extract_decisions(
        self,
        content: str,
    ) -> list[dict[str, str]]:
        """
        Extract decisions/action items from meeting result document.
        
        Args:
            content: Document content
            
        Returns:
            List of decision dictionaries
        """
        prompt = """아래 회의 결과 문서에서 결정 사항과 액션 아이템을 추출해주세요.

## 출력 형식 (JSON):
[
    {
        "agenda_item": "안건명",
        "decision": "결정 내용",
        "assignee": "담당자 (없으면 null)",
        "deadline": "마감일 (없으면 null)"
    }
]

## 문서:
{content}

JSON만 출력하세요.""".format(content=content[:5000])

        try:
            import json
            response = await self.model.generate_content_async(prompt)
            result_text = response.text.strip()
            
            if result_text.startswith("```"):
                result_text = result_text.split("```")[1]
                if result_text.startswith("json"):
                    result_text = result_text[4:]
            
            return json.loads(result_text)
            
        except Exception as e:
            logger.warning("Decision extraction failed", error=str(e))
            return []
