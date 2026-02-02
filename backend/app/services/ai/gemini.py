"""Gemini AI service for LLM and Vision operations."""

import base64
import json
from typing import Any

import google.generativeai as genai

from app.core.config import settings


class GeminiService:
    """Service for Gemini LLM and Vision capabilities."""

    def __init__(self) -> None:
        # Vertex AI가 아닌 Google AI Studio API 키를 사용하는 경우 configure 필요
        # Vertex AI 환경(GCP)이라면 초기화 방식이 다를 수 있으나,
        # 현재 코드 베이스는 api_key 방식을 따릅니다.
        genai.configure(api_key=settings.GEMINI_API_KEY)
        self._model = None
        self._vision_model = None

        # 🚀 [Upgrade] 최신 Gemini 2.0 모델 사용
        # 만약 에러 발생 시 "gemini-1.5-flash-001"로 변경하세요.
        self.MODEL_NAME = "gemini-2.0-flash-lite-001"

    @property
    def model(self):
        """Get text generation model."""
        if self._model is None:
            self._model = genai.GenerativeModel(self.MODEL_NAME)
        return self._model

    @property
    def vision_model(self):
        """Get vision-capable model."""
        if self._vision_model is None:
            self._vision_model = genai.GenerativeModel(self.MODEL_NAME)
        return self._vision_model

    def _parse_json_response(self, response_text: str) -> dict | list:
        """Helper to cleanly parse JSON from LLM response."""
        try:
            json_str = response_text
            if "```json" in response_text:
                json_str = response_text.split("```json")[1].split("```")[0]
            elif "```" in response_text:
                json_str = response_text.split("```")[1].split("```")[0]

            return json.loads(json_str.strip())
        except (json.JSONDecodeError, IndexError):
            # 파싱 실패 시 원본 텍스트를 포함한 에러 구조 반환 또는 빈 값 반환
            return {}

    def generate_text(
        self,
        prompt: str,
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> str:
        """
        Generate text response from a prompt.
        """
        generation_config = genai.GenerationConfig(
            temperature=temperature,
            max_output_tokens=max_tokens,
        )

        try:
            response = self.model.generate_content(
                prompt,
                generation_config=generation_config,
            )
            return response.text
        except Exception as e:
            print(f"Gemini generation error: {e}")
            return "죄송합니다. AI 모델 응답 중 오류가 발생했습니다."

    def analyze_transcript(
        self,
        transcript: str,
        agenda: str | None = None,
    ) -> dict[str, Any]:
        """
        Analyze meeting transcript to extract decisions and action items.
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
        response_text = self.generate_text(prompt, temperature=0.3)
        result = self._parse_json_response(response_text)

        if not result:
            return {
                "summary": response_text,
                "decisions": [],
                "action_items": [],
            }
        return result

    def caption_image(
        self,
        image_bytes: bytes,
        mime_type: str = "image/jpeg",
    ) -> str:
        """
        Generate a caption/description for an image.
        """
        prompt = """이 이미지가 표나 조직도라면 마크다운으로 구조를 텍스트화하고,
일반 사진이라면 상황을 상세 묘사해 줘. 한국어로 작성해주세요."""

        image_part = {
            "inline_data": {
                "mime_type": mime_type,
                "data": base64.b64encode(image_bytes).decode("utf-8"),
            }
        }

        try:
            response = self.vision_model.generate_content([prompt, image_part])
            return response.text
        except Exception as e:
            print(f"Vision generation error: {e}")
            return "이미지 분석 중 오류가 발생했습니다."

    def generate_answer(
        self,
        query: str,
        context: list[str],
        chat_history: str | None = None,
        partner_info: dict | None = None,
    ) -> str:
        """
        Generate an answer based on retrieved context (RAG).
        """
        context_text = "\n\n---\n\n".join(context) if context else "(검색된 문서 없음)"

        history_section = ""
        if chat_history and chat_history != "(이전 대화 없음)":
            history_section = f"""
## 이전 대화 (Context)
{chat_history}
"""

        partner_section = ""
        if partner_info:
            partner_section = f"""
## 제휴 업체 정보 (참고)
{partner_info}
"""

        prompt = f"""당신은 학생회 업무를 돕는 AI 비서 'Council-AI'입니다.

## 역할
- 제공된 [검색된 문서]를 최우선 근거로 사용하여 정확하게 답변합니다.
- [제휴 업체 정보]가 질문과 관련 있다면 적극적으로 안내합니다.
- 문서에 없는 내용은 추측하지 않고, "해당 정보를 문서에서 찾을 수 없습니다"라고 답합니다.
- [이전 대화]의 맥락을 고려하여, 사용자가 '그거', '저거'로 지칭한 대상을 파악합니다.

## 검색된 문서
{context_text}
{partner_section}{history_section}
## 사용자 질문
{query}

## 답변 가이드라인
1. 답변은 한국어로 작성하며, 친절하고 전문적인 톤을 유지합니다.
2. 핵심 결론을 두괄식으로 먼저 제시합니다.
3. 정보가 나열될 경우 마크다운 글머리 기호나 표를 사용해 가독성을 높입니다.
4. 출처가 명확한 경우 "(출처: 문서명)"과 같이 표기합니다.

## 답변:"""

        # RAG 답변은 사실 기반이어야 하므로 temperature를 낮게 설정
        return self.generate_text(prompt, temperature=0.1)

    def extract_calendar_events(self, text: str) -> list[dict[str, Any]]:
        """
        Extract calendar event information from text.
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
        response_text = self.generate_text(prompt, temperature=0.2)
        result = self._parse_json_response(response_text)

        return result if isinstance(result, list) else []
