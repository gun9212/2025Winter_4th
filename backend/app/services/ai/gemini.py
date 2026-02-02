"""Gemini AI service for LLM and Vision operations."""

import base64
from typing import Any

import google.generativeai as genai

from app.core.config import settings


class GeminiService:
    """Service for Gemini LLM and Vision capabilities."""

    def __init__(self) -> None:
        genai.configure(api_key=settings.GEMINI_API_KEY)
        self._model = None
        self._vision_model = None

    @property
    def model(self):
        """Get text generation model (Gemini 1.5 Flash)."""
        if self._model is None:
            self._model = genai.GenerativeModel("gemini-1.5-flash")
        return self._model

    @property
    def vision_model(self):
        """Get vision-capable model."""
        if self._vision_model is None:
            self._vision_model = genai.GenerativeModel("gemini-1.5-flash")
        return self._vision_model

    def generate_text(
        self,
        prompt: str,
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> str:
        """
        Generate text response from a prompt.

        Args:
            prompt: The input prompt.
            temperature: Sampling temperature (0.0-1.0).
            max_tokens: Maximum tokens in response.

        Returns:
            Generated text response.
        """
        generation_config = genai.GenerationConfig(
            temperature=temperature,
            max_output_tokens=max_tokens,
        )

        response = self.model.generate_content(
            prompt,
            generation_config=generation_config,
        )

        return response.text

    def analyze_transcript(
        self,
        transcript: str,
        agenda: str | None = None,
    ) -> dict[str, Any]:
        """
        Analyze meeting transcript to extract decisions and action items.

        Args:
            transcript: Meeting transcript text.
            agenda: Optional agenda document content.

        Returns:
            Dictionary with decisions, action_items, and summary.
        """
        agenda_section = f"회의 안건지:\n{agenda}\n\n" if agenda else ""
        prompt = f"""다음 회의 속기록을 분석하여 결정 사항과 액션 아이템을 추출해주세요.

{agenda_section}회의 속기록:
{transcript}

다음 형식으로 JSON 응답을 해주세요:
{{
    "summary": "회의 요약 (2-3문장)",
    "decisions": [
        {{"topic": "논의 주제", "decision": "결정 내용"}}
    ],
    "action_items": [
        {{"task": "할 일", "assignee": "담당자 (없으면 null)", "due_date": "마감일 (없으면 null)"}}
    ]
}}
"""

        response = self.generate_text(prompt, temperature=0.3)

        # Parse JSON response
        import json

        try:
            # Extract JSON from response (may have markdown code blocks)
            json_str = response
            if "```json" in response:
                json_str = response.split("```json")[1].split("```")[0]
            elif "```" in response:
                json_str = response.split("```")[1].split("```")[0]

            return json.loads(json_str.strip())
        except json.JSONDecodeError:
            return {
                "summary": response,
                "decisions": [],
                "action_items": [],
            }

    def caption_image(
        self,
        image_bytes: bytes,
        mime_type: str = "image/jpeg",
    ) -> str:
        """
        Generate a caption/description for an image.

        Args:
            image_bytes: Image content as bytes.
            mime_type: Image MIME type.

        Returns:
            Image description/caption.
        """
        prompt = """이 이미지가 표나 조직도라면 마크다운으로 구조를 텍스트화하고,
일반 사진이라면 상황을 상세 묘사해 줘. 한국어로 작성해주세요."""

        # Create image part
        image_part = {
            "inline_data": {
                "mime_type": mime_type,
                "data": base64.b64encode(image_bytes).decode("utf-8"),
            }
        }

        response = self.vision_model.generate_content([prompt, image_part])

        return response.text

    def generate_answer(
        self,
        query: str,
        context: list[str],
        chat_history: str | None = None,
        partner_info: dict | None = None,
    ) -> str:
        """
        Generate an answer based on retrieved context (RAG).

        Args:
            query: User's question.
            context: List of relevant document chunks.
            chat_history: Optional formatted conversation history.
            partner_info: Optional partner business info.

        Returns:
            Generated answer.
        """
        context_text = "\n\n---\n\n".join(context) if context else "(검색된 문서 없음)"

        history_section = ""
        if chat_history and chat_history != "(이전 대화 없음)":
            history_section = f"""
## 이전 대화
{chat_history}
"""

        partner_section = ""
        if partner_info:
            partner_section = f"""
## 제휴 업체 정보
{partner_info}
"""

        prompt = f"""당신은 학생회 업무를 돕는 AI 비서 'Council-AI'입니다.

## 역할
- 제공된 문서를 바탕으로 정확하고 친절하게 답변합니다.
- 문서에 없는 내용은 추측하지 않고, "해당 정보를 찾지 못했습니다"라고 답합니다.
- 답변 시 관련 정보의 출처를 자연스럽게 언급합니다.

## 검색된 문서
{context_text}
{partner_section}{history_section}
## 사용자 질문
{query}

## 답변 가이드라인
1. 핵심 정보를 먼저 제공하고, 세부 사항은 이후에 설명합니다.
2. 표나 목록이 적합한 경우 마크다운 형식을 사용합니다.
3. 관련 제휴 업체 정보가 있다면 함께 안내합니다.
4. 불확실한 정보는 "~로 보입니다" 등 완곡하게 표현합니다.
5. 이전 대화가 있다면 맥락을 고려하여 답변합니다.

## 답변:"""

        return self.generate_text(prompt, temperature=0.3)

    def extract_calendar_events(self, text: str) -> list[dict[str, Any]]:
        """
        Extract calendar event information from text.

        Args:
            text: Text containing event information.

        Returns:
            List of event dictionaries.
        """
        prompt = f"""다음 텍스트에서 캘린더에 등록할 일정 정보를 추출해주세요.

텍스트:
{text}

다음 형식의 JSON 배열로 응답해주세요:
[
    {{
        "title": "일정 제목",
        "date": "YYYY-MM-DD",
        "time": "HH:MM (없으면 null)",
        "assignee": "담당자 (없으면 null)",
        "description": "상세 내용"
    }}
]
"""

        response = self.generate_text(prompt, temperature=0.2)

        import json

        try:
            json_str = response
            if "```json" in response:
                json_str = response.split("```json")[1].split("```")[0]
            elif "```" in response:
                json_str = response.split("```")[1].split("```")[0]

            return json.loads(json_str.strip())
        except json.JSONDecodeError:
            return []
