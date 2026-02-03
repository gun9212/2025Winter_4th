"""Query rewriting service for context-aware RAG."""

import structlog

from app.services.ai.gemini import GeminiService

logger = structlog.get_logger()


# Query rewriting prompt template
QUERY_REWRITE_PROMPT = """당신은 대화 맥락을 이해하고 검색 쿼리를 개선하는 AI입니다.

## 작업
이전 대화 내용을 참고하여, 현재 사용자 질문을 **독립적인 검색 쿼리**로 변환하세요.
- 대명사("그거", "이거", "저거", "그것", "거기")를 구체적인 명사로 치환
- 생략된 주어/목적어를 복원
- 검색에 적합한 키워드 중심으로 재구성
- 원래 질문의 의도를 유지

## 이전 대화
{chat_history}

## 현재 질문
{current_query}

## 규칙
1. 변환된 검색 쿼리만 출력하세요. 설명이나 추가 텍스트 없이 쿼리만 반환합니다.
2. 현재 질문이 이미 독립적이라면, 그대로 반환하세요.
3. 질문 형태를 유지하세요 (예: "~인가요?", "~야?" 등).
4. 쿼리는 한국어로 작성하세요.

## 변환된 검색 쿼리:"""


class QueryRewriterService:
    """
    Service for rewriting user queries with conversation context.

    Features:
    - Context-aware query reformulation using LLM
    - Pronoun resolution ("그거" → specific term)

    This service bridges the gap between conversational queries
    and effective vector search queries.
    """

    def __init__(self, gemini: GeminiService) -> None:
        """
        Initialize query rewriter service.

        Args:
            gemini: GeminiService instance for LLM calls.
        """
        self.gemini = gemini

    async def rewrite_query(
        self,
        current_query: str,
        chat_history: str,
    ) -> str:
        """
        Rewrite query using conversation context.

        If chat history is empty or the query appears independent,
        returns the original query.

        Args:
            current_query: User's current question.
            chat_history: Formatted conversation history string.

        Returns:
            Rewritten query suitable for vector search.
        """
        # Skip rewriting if no history
        if chat_history == "(이전 대화 없음)" or not chat_history.strip():
            logger.debug(
                "Skipping query rewrite - no history",
                query=current_query[:50],
            )
            return current_query

        # Skip rewriting if query seems already independent
        if self._is_independent_query(current_query):
            logger.debug(
                "Skipping query rewrite - query appears independent",
                query=current_query[:50],
            )
            return current_query

        try:
            prompt = QUERY_REWRITE_PROMPT.format(
                chat_history=chat_history,
                current_query=current_query,
            )

            rewritten = self.gemini.generate_text(
                prompt=prompt,
                temperature=0.1,  # Low temperature for consistency
                max_tokens=256,
            )

            # Clean up response
            rewritten = rewritten.strip()

            # Validate rewritten query
            if not rewritten or len(rewritten) < 2:
                logger.warning(
                    "Empty rewrite result, using original",
                    original=current_query[:50],
                )
                return current_query

            # Don't use rewritten if it's too different in length
            # (likely LLM hallucinated something)
            if len(rewritten) > len(current_query) * 3:
                logger.warning(
                    "Rewrite too long, using original",
                    original_len=len(current_query),
                    rewrite_len=len(rewritten),
                )
                return current_query

            logger.info(
                "Query rewritten",
                original=current_query[:50],
                rewritten=rewritten[:50],
            )

            return rewritten

        except Exception as e:
            logger.error(
                "Query rewrite failed",
                query=current_query[:50],
                error=str(e),
            )
            # Fallback to original query on error
            return current_query

    def _is_independent_query(self, query: str) -> bool:
        """
        Check if query appears to be already independent.

        A query is considered independent if it doesn't contain
        context-dependent terms like pronouns or references.

        Args:
            query: User's query string.

        Returns:
            True if query appears independent.
        """
        # Context-dependent terms in Korean
        dependent_terms = {
            "그거", "이거", "저거", "그것", "이것", "저것",
            "그건", "이건", "저건", "그게", "이게", "저게",
            "거기", "여기", "저기", "그곳", "이곳", "저곳",
            "그때", "이때", "그날", "그분", "이분",
            "위에서", "아까", "방금", "앞서",
            "말한", "말씀하신", "언급한", "얘기한",
        }

        query_lower = query.lower()

        for term in dependent_terms:
            if term in query_lower:
                return False

        return True
