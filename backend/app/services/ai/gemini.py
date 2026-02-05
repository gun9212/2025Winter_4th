"""Gemini AI service for LLM and Vision operations."""

import base64
import json
from typing import Any

import google.generativeai as genai
import structlog

from app.core.config import settings

logger = structlog.get_logger()


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
        self.MODEL_NAME = "gemini-flash-latest"

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
            logger.error("Gemini generation error", error=str(e))
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
            logger.error("Vision generation error", error=str(e))
            return "이미지 분석 중 오류가 발생했습니다."

    def generate_answer(
        self,
        query: str,
        context: list[str],
        chat_history: str | None = None,
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

        prompt = f"""당신은 학생회 업무를 돕는 AI 비서 'Council-AI'입니다.

## 역할
- 제공된 [검색된 문서]를 최우선 근거로 사용하여 정확하게 답변합니다.
- 문서에 없는 내용은 추측하지 않고, "해당 정보를 문서에서 찾을 수 없습니다"라고 답합니다.
- [이전 대화]의 맥락을 고려하여, 사용자가 '그거', '저거'로 지칭한 대상을 파악합니다.

## 검색된 문서
{context_text}
{history_section}
## 사용자 질문
{query}

## 답변 가이드라인
1. 답변은 한국어로 작성하며, 친절하고 전문적인 톤을 유지합니다.
2. 핵심 결론을 두괄식으로 먼저 제시합니다.
3. 정보가 나열될 경우 마크다운 글머리 기호나 표를 사용해 가독성을 높입니다.
4. 출처가 명확한 경우 "(출처: 문서명)"과 같이 표기합니다.
5. 날짜나 연도를 묻는 질문의 경우, 문서 내용에서 날짜 정보(예: "2025.05.01", "5월", "제37대" 등)를 적극적으로 찾아 답변합니다.

## 답변:"""

        # RAG 답변은 사실 기반이어야 하므로 temperature를 낮게 설정
        # max_tokens를 8192로 늘려 긴 답변도 잘리지 않게 함
        return self.generate_text(prompt, temperature=0.1, max_tokens=8192)

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

    # =========================================================================
    # Smart Minutes Feature Methods
    # =========================================================================

    def summarize_agenda_section(
        self,
        section_content: str,
        section_title: str,
        agenda_type: str = "discuss",
    ) -> dict[str, Any]:
        """
        Summarize a single agenda section from transcript for Smart Minutes.
        
        Args:
            section_content: Content of the agenda section (발언 기록)
            section_title: Title of the agenda item
            agenda_type: Type of agenda (report, discuss, decision, other)
            
        Returns:
            Dict with 'summary', 'has_decision', 'action_items'
        """
        type_guidance = {
            "report": "보고 안건입니다. 주요 보고 내용을 간략히 정리하세요.",
            "discuss": "논의 안건입니다. 결정된 사항이 있으면 명시하고, 없으면 '논의 진행 중'으로 표시하세요.",
            "decision": "의결 안건입니다. 의결 결과(가결/부결/보류)를 명확히 표시하세요.",
            "other": "기타 안건입니다. 핵심 내용만 간략히 요약하세요.",
        }
        
        guidance = type_guidance.get(agenda_type, type_guidance["other"])
        
        prompt = f"""당신은 학생회 회의록 작성 전문가입니다.

## 안건 정보
- 제목: {section_title}
- 유형: {agenda_type} ({guidance})

## 속기 내용
{section_content}

## 작업
위 속기 내용을 분석하여 [결과지]에 기입할 내용을 작성하세요.

## 출력 형식 (JSON)
{{
    "summary": "결과지에 기입할 요약 (1-3문장, 결론 위주)",
    "has_decision": true/false,
    "decisions": ["결정사항1", "결정사항2"],
    "action_items": [
        {{"task": "할 일", "assignee": "담당자 또는 null", "deadline": "마감일 또는 null"}}
    ],
    "discussion_progress": "결정 없을 시 논의 진전 상황"
}}

JSON만 출력하세요."""

        response_text = self.generate_text(prompt, temperature=0.2)
        result = self._parse_json_response(response_text)
        
        if not result:
            return {
                "summary": "요약 생성 실패",
                "has_decision": False,
                "decisions": [],
                "action_items": [],
                "discussion_progress": "",
            }
        
        return result

    def extract_todos_from_document(
        self,
        content: str,
        include_context: bool = True,
    ) -> list[dict[str, Any]]:
        """
        Extract todo/action items from a result document for Calendar Sync.
        
        Enhanced for Korean meeting transcripts (대화형 속기록).
        
        Args:
            content: Full text content of the result document
            include_context: Whether to include source context
            
        Returns:
            List of todo items with content, assignee, deadline, context
        """
        # Few-shot example for transcript-style content
        example_transcript = """예시 입력:
홍길동: 다음 MT 장소는 제가 알아볼게요. 이번 주 금요일까지 후보 정리해서 공유드리겠습니다.
김철수: 네, 그럼 예산안은 제가 작성할게요. 다음 회의 전까지 초안 만들어놓을게요.
"""
        example_output = """예시 출력:
[
    {"content": "MT 장소 후보 조사 및 정리", "context": "MT 관련 논의", "assignee": "홍길동", "suggested_date": "이번 주 금요일", "parsed_date": null},
    {"content": "예산안 초안 작성", "context": "MT 관련 논의", "assignee": "김철수", "suggested_date": "다음 회의 전", "parsed_date": null}
]"""

        prompt = f"""당신은 학생회 회의록 분석 전문가입니다.
산발적인 대화 속에서도 '행동이 필요한 작업(Action Item)'을 정확히 식별합니다.

## 분석 대상 텍스트
{content[:10000]}

## 추출 기준
1. **발화에서 유추**: "제가 할게요", "맡겠습니다", "알아볼게요", "확인해보겠습니다" 등
2. **명시적 지시**: "~해주세요", "~부탁드립니다", "담당: 누구"
3. **마감 언급**: "언제까지", "다음 주", "금요일", "회의 전까지"
4. **결정 사항**: "~로 결정", "~하기로 함" (이것도 후속 조치가 필요하면 추출)

*중요: 대화형 속기록에서도 발화자의 약속이나 의지 표현을 Action Item으로 인식하세요.*
*할 일이 전혀 없어 보여도, 회의에서 논의된 후속 조치가 있다면 추출하세요.*

## Few-shot 예시
{example_transcript}
{example_output}

## 실제 분석 대상
위 텍스트에서 할 일(Action Item)을 추출하세요.

## 출력 형식 (JSON 배열만 출력)
[
    {{
        "content": "구체적인 할 일 내용",
        "context": "관련 안건 또는 발언 맥락",
        "assignee": "담당자 이름/직책 (없으면 null)",
        "suggested_date": "언급된 마감일 텍스트 (없으면 null)",
        "parsed_date": "YYYY-MM-DD 형식 (파싱 불가 시 null)"
    }}
]

반드시 JSON 배열만 출력하세요. 설명이나 주석을 추가하지 마세요.
할 일이 없으면 빈 배열 []을 출력하세요."""

        response_text = self.generate_text(prompt, temperature=0.2)
        
        # Debug logging for response analysis
        logger.debug(
            "Gemini todo extraction response",
            response_preview=response_text[:500] if response_text else "(empty)",
            response_length=len(response_text) if response_text else 0,
        )
        
        result = self._parse_json_response(response_text)
        
        # Additional logging for parsing result
        if not isinstance(result, list):
            logger.warning(
                "Todo extraction returned non-list",
                result_type=type(result).__name__,
                response_preview=response_text[:300] if response_text else "(empty)",
            )
            return []
        
        logger.info(
            "Todo extraction parsed successfully",
            todos_count=len(result),
        )
        
        return result

    def generate_handover_insight(
        self,
        event_title: str,
        event_content: str,
    ) -> dict[str, Any]:
        """
        Generate deep analysis for a single event based on its document content.
        
        This function reads actual meeting transcripts, agendas, and results
        to produce strategic insights for the next student council.
        
        Args:
            event_title: Title of the event/project
            event_content: Aggregated preprocessed_content from related documents
            
        Returns:
            Dict with keys: overview, key_decisions, success_points,
                            improvement_points, next_year_advice
        """
        # Limit content to prevent context overflow
        content_truncated = event_content[:15000] if event_content else "(문서 내용 없음)"
        
        prompt = f"""당신은 학생회 인수인계 담당자입니다.
후배 학생회가 내년에 이 행사를 더 잘 운영할 수 있도록 분석해주세요.

## 행사명
{event_title}

## 관련 문서 내용 (회의록, 안건지, 결과지 등)
{content_truncated}

## 분석 요청
위 문서 내용을 바탕으로 다음 항목을 분석하세요:
1. 행사 개요 (언제, 어디서, 무엇을)
2. 주요 결정사항 (구체적인 팩트 위주)
3. 잘한 점 (성공 요인)
4. 아쉬운 점 / 개선 필요 사항
5. 내년 담당자를 위한 구체적인 조언

## 출력 형식 (JSON)
{{
    "overview": "행사 개요 요약 (1-2문장)",
    "key_decisions": ["주요 결정사항1", "주요 결정사항2"],
    "success_points": ["잘한 점1", "잘한 점2"],
    "improvement_points": ["아쉬운 점1", "개선 필요 사항2"],
    "next_year_advice": "내년 담당자를 위한 구체적인 조언 (3-5문장)"
}}

JSON만 출력하세요. 문서에 정보가 부족하면 해당 항목은 빈 배열이나 "(정보 부족)"으로 표시하세요."""

        response_text = self.generate_text(prompt, temperature=0.3)
        result = self._parse_json_response(response_text)
        
        if not result:
            return {
                "overview": "(분석 실패)",
                "key_decisions": [],
                "success_points": [],
                "improvement_points": [],
                "next_year_advice": "(분석 실패)",
            }
        
        return result

    def generate_handover_content(
        self,
        events_data: list[dict[str, Any]],
        year: int,
        department: str | None = None,
        include_insights: bool = True,
    ) -> str:
        """
        Generate comprehensive handover document content.
        
        Args:
            events_data: List of event dictionaries with title, date, summary, etc.
            year: Target year
            department: Optional department filter
            include_insights: Whether to include AI insights
            
        Returns:
            Markdown formatted handover content
        """
        dept_text = f"{department} " if department else ""
        
        # Format events for prompt
        events_text = ""
        for event in events_data[:30]:  # Limit to prevent context overflow
            events_text += f"""
### {event.get('title', '제목 없음')}
- 날짜: {event.get('event_date', '미정')}
- 담당: {event.get('category', '미정')}
- 상태: {event.get('status', '미정')}
- 요약: {event.get('summary', '(요약 없음)')}
"""
        
        insights_instruction = """
## 7. 차기 학생회를 위한 제언
- 전체 사업 운영에 대한 인사이트
- 개선이 필요한 부분
- 유지하면 좋을 것들
""" if include_insights else ""
        
        prompt = f"""당신은 학생회 인수인계서 작성 전문가입니다.

## 작성 대상
- 연도: {year}년
- 대상: {dept_text}학생회

## 행사/사업 데이터
{events_text}

## 인수인계서 구조
다음 구조에 맞춰 Markdown 형식의 인수인계서를 작성하세요:

# 제38대 {dept_text}학생회 인수인계서 ({year})

## 1. 개요
- {year}년 학생회 활동 전반에 대한 소개

## 2. 조직 구성
- 주요 보직 및 담당 업무

## 3. 주요 사업 총괄
- 연간 사업 타임라인
- 주요 성과

## 4. 사업별 상세 기록
(각 행사에 대한 기획 의도, 진행 과정, 결과, 피드백)

## 5. 예산 운용 개요
- 주요 지출 항목
- 예산 관리 팁

## 6. 주요 결정사항 아카이브
- 중요한 의사결정 기록
{insights_instruction}

위 데이터를 바탕으로 실질적으로 도움이 되는 인수인계서를 작성하세요.
없는 정보는 추측하지 말고 "(정보 없음)" 또는 "(추가 필요)"로 표시하세요.
"""

        return self.generate_text(prompt, temperature=0.4, max_tokens=8000)
