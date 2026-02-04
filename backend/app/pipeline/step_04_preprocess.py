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
PREPROCESSING_PROMPT = """당신은 서울대학교 컴퓨터공학부 학생회 회의록 구조화 전문가입니다.

아래 회의 문서를 분석하여 Markdown 헤더 구조를 추가해주세요.

## 🚨 최우선 규칙 (반드시 준수):
1. **원본 텍스트를 100% 유지하세요**
   - 모든 문장, 모든 단어, 모든 표, 모든 리스트를 그대로 출력
   - 어떤 내용도 생략, 요약, 축약 절대 금지
   - 입력 문서 길이와 출력 문서 길이가 거의 동일해야 함
   
2. **헤더만 삽입**
   - 오직 `#`와 `##` 헤더만 적절한 위치에 추가
   - 원본의 줄바꿈, 공백도 유지

3. **기존 `#`, `##` 헤더는 무시**
   - 파서가 임의로 생성한 헤더이므로 제거하고 새로 구조화

## 📋 헤더 구조 규칙:
1. **안건 종류**는 `#` (H1) 헤더로 표시
   - 예: `# 보고안건`, `# 논의안건`, `# 기타안건`
   
2. **개별 안건**은 `##` (H2) 헤더로 표시
   - 예: `## 보고안건 1. 학생회장단 활동보고`
   - 예: `## 논의안건 2. 2025 컴밤, 컴낮`

## 🔍 안건 파악 방법:
- **문서 상단에 안건 요약표가 있습니다** (항상 존재)
- 형식: `| 안건 | <보고안건> 1. 제목 2. 제목 <논의안건> 1. 제목 ... |`
- 이 요약표를 참고하여 본문의 각 안건 시작 위치에 헤더를 삽입

## 출력:
- Markdown 형식
- 원본 내용 100% 포함 + 헤더 구조만 추가
- 설명이나 주석 없이 결과물만 출력

## 입력 문서:
{content}

---
위 문서를 안건 기준으로 헤더 구조화하여 **전체 내용을 유지하며** 출력하세요."""


# Prompt for non-meeting documents (simpler structure)
SIMPLE_PREPROCESSING_PROMPT = """아래 문서의 내용을 정리하여 Markdown 형식으로 변환해주세요.

## ⚠️ 절대 규칙:
- **원본 텍스트를 한 글자도 수정하지 마세요**
- 내용 요약, 생략, 재작성 금지
- 기존 `#`, `##` 헤더는 제거하고 새로 구조화

## 규칙:
1. 주요 섹션은 `##` 헤더로 표시
2. 기존 구조와 내용 유지
3. 불필요한 공백이나 서식만 정리

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
        # Increase max_output_tokens to prevent content truncation
        self.model = genai.GenerativeModel(
            settings.GEMINI_MODEL,
            generation_config=genai.GenerationConfig(
                max_output_tokens=32000,  # Max for Gemini 2.0 Flash
                temperature=0.1,  # Low temperature for more faithful output
            ),
        )

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

            # Log content length comparison to detect loss
            original_len = len(content)
            processed_len = len(processed_content)
            loss_ratio = 1 - (processed_len / original_len) if original_len > 0 else 0
            
            logger.info(
                "Preprocessing complete",
                original_length=original_len,
                processed_length=processed_len,
                loss_ratio=f"{loss_ratio:.1%}",
            )
            
            # If severe content loss (>50%), fall back to original with basic cleanup
            if loss_ratio > 0.5:
                logger.warning(
                    "Severe content loss detected, using original content",
                    loss_ratio=f"{loss_ratio:.1%}",
                )
                processed_content = self._basic_cleanup(content)

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
