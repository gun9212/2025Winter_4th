"""
Unit tests for text_utils.py - split_by_headers and DocumentSection.

Tests cover:
1. Normal Markdown parsing with # and ## headers
2. Edge case: No headers (plain text)
3. Edge case: Only ## headers (no H1)
4. Agenda type and number extraction
5. Placeholder key generation
"""

import pytest
from app.services.text_utils import split_by_headers, DocumentSection


class TestSplitByHeaders:
    """Test split_by_headers function."""

    def test_normal_markdown_with_h1_and_h2(self):
        """Scenario 1: Normal Markdown with H1 and H2 headers."""
        content = """# 보고안건

문화국 보고 내용입니다.

## 보고안건 1. 학생회장단 활동보고

학생회장: 지난 주 총장님과 면담을 진행했습니다.
부회장: 예산 집행 현황을 보고드립니다.

## 보고안건 2. 문화국 활동보고

문화국장: 축제 준비 상황을 보고드립니다.

# 논의안건

## 논의안건 1. 컴씨 장소 선정

학생회장: 오크밸리와 용평 중 선택해야 합니다.
"""
        sections = split_by_headers(content, max_level=2)
        
        # Should have 5 sections: H1 보고안건, H2 보고1, H2 보고2, H1 논의안건, H2 논의1
        assert len(sections) == 5
        
        # Check H1 sections
        assert sections[0].header_level == 1
        assert sections[0].title == "보고안건"
        
        # Check H2 sections
        assert sections[1].header_level == 2
        assert sections[1].title == "보고안건 1. 학생회장단 활동보고"
        assert "학생회장" in sections[1].content
        
        # Check agenda type extraction for H2
        assert sections[1].agenda_type == "report"
        assert sections[1].agenda_number == 1
        
        # Check placeholder key
        assert sections[1].placeholder_key == "{report_1_result}"

    def test_no_headers_fallback(self):
        """Scenario 2: Plain text without any headers - should return single section."""
        content = """이것은 헤더가 없는 일반 텍스트입니다.
        
여러 줄로 구성되어 있지만
마크다운 헤더는 포함되어 있지 않습니다.

다음 줄도 마찬가지입니다."""
        
        sections = split_by_headers(content, max_level=2)
        
        # Should return exactly one section with all content
        assert len(sections) == 1
        assert sections[0].header_level == 0
        assert sections[0].title == "전체 내용"
        assert "헤더가 없는" in sections[0].content
        assert sections[0].agenda_type is None
        assert sections[0].placeholder_key is None

    def test_only_h2_headers_no_h1(self):
        """Scenario 3: Only ## headers without # headers."""
        content = """## 논의안건 1. 축제 예산

예산 관련 논의입니다.

## 논의안건 2. MT 장소

MT 장소 관련 논의입니다."""
        
        sections = split_by_headers(content, max_level=2)
        
        # Should parse both H2 sections
        assert len(sections) == 2
        assert all(s.header_level == 2 for s in sections)
        
        # Check first section
        assert sections[0].title == "논의안건 1. 축제 예산"
        assert sections[0].agenda_type == "discuss"
        assert sections[0].agenda_number == 1
        assert sections[0].placeholder_key == "{discuss_1_result}"
        
        # Check second section
        assert sections[1].title == "논의안건 2. MT 장소"
        assert sections[1].agenda_type == "discuss"
        assert sections[1].agenda_number == 2

    def test_h1_only_max_level_1(self):
        """Test max_level=1 only parses H1 headers."""
        content = """# 보고안건

내용

## 보고안건 1. 세부

세부 내용

# 논의안건

논의 내용"""
        
        sections = split_by_headers(content, max_level=1)
        
        # Should only find H1 headers
        assert len(sections) == 2
        assert sections[0].title == "보고안건"
        assert sections[1].title == "논의안건"


class TestDocumentSectionAgendaType:
    """Test DocumentSection.agenda_type property."""

    def test_h1_report_type(self):
        """H1 with 보고 keyword."""
        section = DocumentSection(
            header_level=1,
            header_text="# 보고안건",
            title="보고안건",
            content="",
            start_index=0,
            end_index=10,
        )
        assert section.agenda_type == "report"

    def test_h1_discuss_type(self):
        """H1 with 논의 keyword."""
        section = DocumentSection(
            header_level=1,
            header_text="# 논의안건",
            title="논의안건",
            content="",
            start_index=0,
            end_index=10,
        )
        assert section.agenda_type == "discuss"

    def test_h2_report_with_number(self):
        """H2 with 보고안건 N. pattern."""
        section = DocumentSection(
            header_level=2,
            header_text="## 보고안건 1. 학생회장단 활동보고",
            title="보고안건 1. 학생회장단 활동보고",
            content="",
            start_index=0,
            end_index=10,
        )
        assert section.agenda_type == "report"
        assert section.agenda_number == 1

    def test_h2_discuss_with_number(self):
        """H2 with 논의안건 N. pattern."""
        section = DocumentSection(
            header_level=2,
            header_text="## 논의안건 2. 컴씨 장소",
            title="논의안건 2. 컴씨 장소",
            content="",
            start_index=0,
            end_index=10,
        )
        assert section.agenda_type == "discuss"
        assert section.agenda_number == 2

    def test_h2_other_type(self):
        """H2 with 기타안건 pattern."""
        section = DocumentSection(
            header_level=2,
            header_text="## 기타안건 1. 공지사항",
            title="기타안건 1. 공지사항",
            content="",
            start_index=0,
            end_index=10,
        )
        assert section.agenda_type == "other"
        assert section.agenda_number == 1

    def test_h2_decision_type(self):
        """H2 with 의결안건 pattern."""
        section = DocumentSection(
            header_level=2,
            header_text="## 의결안건 1. 예산안 의결",
            title="의결안건 1. 예산안 의결",
            content="",
            start_index=0,
            end_index=10,
        )
        assert section.agenda_type == "decision"

    def test_unknown_type_returns_none(self):
        """H2 without recognized agenda type keyword."""
        section = DocumentSection(
            header_level=2,
            header_text="## 1. 인사말",
            title="1. 인사말",
            content="",
            start_index=0,
            end_index=10,
        )
        # Number pattern at start doesn't have type keyword
        assert section.agenda_type is None
        # But number should still be extracted
        assert section.agenda_number == 1


class TestDocumentSectionPlaceholderKey:
    """Test DocumentSection.placeholder_key property."""

    def test_placeholder_with_type_and_number(self):
        """Placeholder generated with type and number."""
        section = DocumentSection(
            header_level=2,
            header_text="## 보고안건 1. 제목",
            title="보고안건 1. 제목",
            content="",
            start_index=0,
            end_index=10,
        )
        assert section.placeholder_key == "{report_1_result}"

    def test_placeholder_h1_with_type_only(self):
        """H1 has agenda_type but no number."""
        section = DocumentSection(
            header_level=1,
            header_text="# 보고안건",
            title="보고안건",
            content="",
            start_index=0,
            end_index=10,
        )
        # H1 has type but no number (agenda_number only works for H2)
        assert section.agenda_type == "report"
        assert section.agenda_number is None
        assert section.placeholder_key == "{report_result}"

    def test_placeholder_none_when_no_type(self):
        """No placeholder when agenda_type is None."""
        section = DocumentSection(
            header_level=2,
            header_text="## 기타",
            title="기타",
            content="",
            start_index=0,
            end_index=10,
        )
        # "기타" alone doesn't match "기타안건" pattern for H2
        assert section.agenda_type is None
        assert section.placeholder_key is None


class TestAgendaNumberExtraction:
    """Test various agenda number patterns."""

    def test_pattern_angeun_number(self):
        """Pattern: 안건 N."""
        section = DocumentSection(
            header_level=2,
            header_text="## 논의안건 3. 제목",
            title="논의안건 3. 제목",
            content="",
            start_index=0,
            end_index=10,
        )
        assert section.agenda_number == 3

    def test_pattern_parenthesis(self):
        """Pattern: N) format."""
        section = DocumentSection(
            header_level=2,
            header_text="## 보고안건 2) 제목",
            title="보고안건 2) 제목",
            content="",
            start_index=0,
            end_index=10,
        )
        assert section.agenda_number == 2

    def test_pattern_number_at_start(self):
        """Pattern: N. at start of title."""
        section = DocumentSection(
            header_level=2,
            header_text="## 1. 첫번째 안건",
            title="1. 첫번째 안건",
            content="",
            start_index=0,
            end_index=10,
        )
        assert section.agenda_number == 1

    def test_no_number_h1(self):
        """H1 headers should not extract numbers."""
        section = DocumentSection(
            header_level=1,
            header_text="# 보고안건 1",
            title="보고안건 1",
            content="",
            start_index=0,
            end_index=10,
        )
        # H1 should return None for agenda_number
        assert section.agenda_number is None



# Run tests: pytest backend/tests/unit/test_text_utils.py -v


class TestCleanMarkdown:
    """Test clean_markdown function for Google Docs insertion."""

    def test_remove_bold(self):
        """Remove **bold** formatting."""
        from app.services.text_utils import clean_markdown
        
        result = clean_markdown("**결정사항**: 오크밸리로 선정")
        assert result == "결정사항: 오크밸리로 선정"
        
        result = clean_markdown("__underline bold__ text")
        assert result == "underline bold text"

    def test_remove_italic(self):
        """Remove *italic* formatting."""
        from app.services.text_utils import clean_markdown
        
        result = clean_markdown("*강조된* 텍스트")
        assert result == "강조된 텍스트"
        
        result = clean_markdown("_이탤릭_ 스타일")
        assert result == "이탤릭 스타일"

    def test_remove_headers(self):
        """Remove # ## ### headers at line start."""
        from app.services.text_utils import clean_markdown
        
        result = clean_markdown("## 결과 요약\n내용입니다.")
        assert result == "결과 요약\n내용입니다."
        
        result = clean_markdown("### 세부사항")
        assert result == "세부사항"

    def test_convert_bullet_points(self):
        """Convert - * bullet points to • character."""
        from app.services.text_utils import clean_markdown
        
        result = clean_markdown("- 첫 번째 항목\n- 두 번째 항목")
        assert result == "• 첫 번째 항목\n• 두 번째 항목"
        
        result = clean_markdown("* 항목 A\n* 항목 B")
        assert result == "• 항목 A\n• 항목 B"

    def test_remove_inline_code(self):
        """Remove `inline code` backticks."""
        from app.services.text_utils import clean_markdown
        
        result = clean_markdown("함수 `calculate()` 호출")
        assert result == "함수 calculate() 호출"

    def test_remove_code_blocks(self):
        """Remove ``` code blocks entirely."""
        from app.services.text_utils import clean_markdown
        
        result = clean_markdown("시작\n```python\nprint('hello')\n```\n끝")
        assert result == "시작\n\n끝"

    def test_remove_links(self):
        """Convert [text](url) to just text."""
        from app.services.text_utils import clean_markdown
        
        result = clean_markdown("자세한 내용은 [문서](https://example.com)를 참고하세요.")
        assert result == "자세한 내용은 문서를 참고하세요."

    def test_empty_string(self):
        """Handle empty string gracefully."""
        from app.services.text_utils import clean_markdown
        
        result = clean_markdown("")
        assert result == ""
        
        result = clean_markdown(None)
        assert result is None

    def test_preserve_numbers(self):
        """Keep numbered lists."""
        from app.services.text_utils import clean_markdown
        
        result = clean_markdown("1. 첫 번째\n2. 두 번째")
        assert "1." in result
        assert "2." in result


class TestCleanSummaryForDocs:
    """Test clean_summary_for_docs function."""

    def test_basic_summary(self):
        """Extract and clean basic summary."""
        from app.services.text_utils import clean_summary_for_docs
        
        result = clean_summary_for_docs({
            "summary": "**오크밸리**로 결정됨",
            "decisions": [],
            "action_items": []
        })
        assert "오크밸리로 결정됨" in result
        assert "**" not in result

    def test_with_decisions(self):
        """Include decisions section."""
        from app.services.text_utils import clean_summary_for_docs
        
        result = clean_summary_for_docs({
            "summary": "회의 결과",
            "decisions": ["장소 확정", "예산 승인"],
            "action_items": []
        })
        assert "[결정사항]" in result
        assert "• 장소 확정" in result
        assert "• 예산 승인" in result

    def test_with_action_items(self):
        """Include action items with assignee and deadline."""
        from app.services.text_utils import clean_summary_for_docs
        
        result = clean_summary_for_docs({
            "summary": "요약",
            "decisions": [],
            "action_items": [
                {"task": "예산안 작성", "assignee": "문화국", "deadline": "4/20"}
            ]
        })
        assert "[할 일]" in result
        assert "예산안 작성" in result
        assert "(담당: 문화국)" in result
        assert "(기한: 4/20)" in result

    def test_discussion_progress_fallback(self):
        """Show discussion progress when no decisions."""
        from app.services.text_utils import clean_summary_for_docs
        
        result = clean_summary_for_docs({
            "summary": "논의 중",
            "decisions": [],
            "action_items": [],
            "discussion_progress": "다음 회의에서 재논의 예정"
        })
        assert "[논의 현황]" in result
        assert "다음 회의에서 재논의 예정" in result

    def test_empty_result(self):
        """Handle empty or missing fields."""
        from app.services.text_utils import clean_summary_for_docs
        
        result = clean_summary_for_docs({})
        assert result == ""
        
        result = clean_summary_for_docs({"summary": ""})
        assert result == ""
