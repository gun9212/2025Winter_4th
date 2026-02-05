"""Text processing utilities for document analysis.

Refactored from step_04_preprocess.py for reuse across features:
- Smart Minutes (transcript section splitting)
- Calendar Sync (todo extraction)
- Handover (document summarization)
"""

import re
from dataclasses import dataclass

import structlog

logger = structlog.get_logger()


@dataclass
class DocumentSection:
    """A section of a document split by headers."""
    
    header_level: int  # 1 for #, 2 for ##, 3 for ###
    header_text: str  # Full header text (e.g., "# 보고안건")
    title: str  # Just the title part (e.g., "보고안건")
    content: str  # Content under this header
    start_index: int  # Character index where this section starts
    end_index: int  # Character index where this section ends
    
    @property
    def agenda_type(self) -> str | None:
        """
        Extract agenda type from header.
        
        Supports two patterns:
        1. H1 headers: "# 보고안건", "# 논의안건"
        2. H2 headers: "## 보고안건 1. 제목", "## 논의안건 2. 컴씨"
        
        Returns:
            "report", "discuss", "decision", "other", or None
        """
        title = self.title
        
        # Pattern 1: H1 style - "# 보고안건" (agenda category header)
        if self.header_level == 1:
            if "보고" in title:
                return "report"
            elif "논의" in title:
                return "discuss"
            elif "의결" in title:
                return "decision"
            elif "기타" in title:
                return "other"
        
        # Pattern 2: H2 style - "## 보고안건 1. 제목" (individual agenda item)
        if self.header_level == 2:
            if "보고안건" in title or "보고 안건" in title:
                return "report"
            elif "논의안건" in title or "논의 안건" in title:
                return "discuss"
            elif "의결안건" in title or "의결 안건" in title:
                return "decision"
            elif "기타안건" in title or "기타 안건" in title:
                return "other"
            # Fallback: check for type keyword at start
            elif title.startswith("보고"):
                return "report"
            elif title.startswith("논의"):
                return "discuss"
        
        return None
    
    @property
    def agenda_number(self) -> int | None:
        """
        Extract agenda item number if present.
        
        Supports patterns:
        - "논의안건 2. 제목" -> 2
        - "보고안건 1) 제목" -> 1
        - "논의 3. 컴씨" -> 3
        - "1. 제목" -> 1
        
        Only extracts from H2 headers (individual agenda items).
        
        Returns:
            Agenda number or None
        """
        if self.header_level != 2:
            return None
        
        # Pattern 1: "안건 N." or "안건N."
        match = re.search(r'안건\s*(\d+)[.)\s]', self.title)
        if match:
            return int(match.group(1))
        
        # Pattern 2: Type followed by number - "보고 1." "논의 2."
        match = re.search(r'(?:보고|논의|의결|기타)\s*(\d+)[.)\s]', self.title)
        if match:
            return int(match.group(1))
        
        # Pattern 3: Number at start - "1. 제목"
        match = re.search(r'^(\d+)[.)\s]', self.title.strip())
        if match:
            return int(match.group(1))
        
        return None
    
    @property
    def placeholder_key(self) -> str | None:
        """
        Generate placeholder key for this section.
        
        Returns:
            Placeholder like "{report_1_result}" or None
        """
        agenda_type = self.agenda_type
        agenda_num = self.agenda_number
        
        if agenda_type and agenda_num:
            return f"{{{agenda_type}_{agenda_num}_result}}"
        elif agenda_type:
            # Fallback for unnumbered items
            return f"{{{agenda_type}_result}}"
        return None


def split_by_headers(
    content: str,
    max_level: int = 2,
) -> list[DocumentSection]:
    """
    Split document content by Markdown headers.
    
    This is the core logic refactored from step_04_preprocess.py.
    Used by Smart Minutes to split transcript by agenda items.
    
    Args:
        content: Document content (Markdown with headers)
        max_level: Maximum header level to split on (1=# only, 2=# and ##)
        
    Returns:
        List of DocumentSection objects
        
    Example:
        >>> content = '''# 보고안건
        ... 문화국 보고 내용...
        ... ## 논의안건 1. 컴씨 장소
        ... 학생회장: 오크밸리로 결정
        ... '''
        >>> sections = split_by_headers(content)
        >>> len(sections)
        2
    """
    # Pattern to match headers up to max_level
    # Captures: (header_marks, title_text)
    header_pattern = rf'^(#{{{1},{max_level}}})\s+(.+)$'
    
    sections: list[DocumentSection] = []
    current_pos = 0
    
    # Find all headers
    matches = list(re.finditer(header_pattern, content, re.MULTILINE))
    
    if not matches:
        # No headers found, return entire content as single section
        return [DocumentSection(
            header_level=0,
            header_text="",
            title="전체 내용",
            content=content.strip(),
            start_index=0,
            end_index=len(content),
        )]
    
    for i, match in enumerate(matches):
        header_marks = match.group(1)
        header_title = match.group(2).strip()
        header_level = len(header_marks)
        
        # Determine content end (next header or end of document)
        if i + 1 < len(matches):
            content_end = matches[i + 1].start()
        else:
            content_end = len(content)
        
        # Extract content (everything after header line until next header)
        content_start = match.end() + 1  # +1 to skip newline
        section_content = content[content_start:content_end].strip()
        
        sections.append(DocumentSection(
            header_level=header_level,
            header_text=match.group(0),
            title=header_title,
            content=section_content,
            start_index=match.start(),
            end_index=content_end,
        ))
    
    return sections


def extract_headers(content: str) -> list[str]:
    """
    Extract all Markdown headers from content.
    
    Args:
        content: Document content
        
    Returns:
        List of header strings (e.g., ['# 보고안건', '## 논의안건 1'])
    """
    pattern = r'^(#{1,3})\s+(.+)$'
    headers = []
    for match in re.finditer(pattern, content, re.MULTILINE):
        headers.append(f"{match.group(1)} {match.group(2)}")
    return headers


def normalize_whitespace(content: str) -> str:
    """
    Normalize whitespace in content.
    
    - Converts Windows line endings to Unix
    - Removes excessive blank lines (more than 2 consecutive)
    - Strips trailing whitespace from lines
    
    Args:
        content: Raw text content
        
    Returns:
        Cleaned content
    """
    # Normalize line breaks
    content = content.replace("\r\n", "\n").replace("\r", "\n")
    
    # Remove excessive blank lines (more than 2 consecutive)
    content = re.sub(r'\n{3,}', '\n\n', content)
    
    # Strip trailing whitespace from lines
    lines = [line.rstrip() for line in content.split('\n')]
    content = '\n'.join(lines)
    
    return content.strip()


def extract_speaker_statements(content: str) -> list[dict[str, str]]:
    """
    Extract speaker statements from transcript content.
    
    Format: "{발언자}: {발언 내용}" or "{직책}: {발언 내용}"
    
    Args:
        content: Transcript content
        
    Returns:
        List of dicts with 'speaker' and 'statement' keys
        
    Example:
        >>> content = "학생회장: 오크밸리로 결정합시다.\\n부학생회장: 동의합니다."
        >>> statements = extract_speaker_statements(content)
        >>> statements[0]
        {'speaker': '학생회장', 'statement': '오크밸리로 결정합시다.'}
    """
    # Pattern: starts with speaker name/title, followed by colon
    # Speaker can be: 학생회장, 부학생회장, 문화국장, 복지국장, 디홍국장, 사무국장, or names
    pattern = r'^([가-힣]+(?:장|원)?)\s*:\s*(.+)$'
    
    statements = []
    for match in re.finditer(pattern, content, re.MULTILINE):
        statements.append({
            'speaker': match.group(1).strip(),
            'statement': match.group(2).strip(),
        })
    
    return statements


def extract_decisions(content: str) -> list[str]:
    """
    Extract decision keywords and patterns from content.
    
    Looks for patterns like:
    - "=> 결정", "-> 결정"
    - "로 결정", "으로 선정"
    - "확정", "승인"
    
    Args:
        content: Document content
        
    Returns:
        List of sentences containing decisions
    """
    decision_patterns = [
        r'[=\-]>\s*(.+결정.+)',
        r'(.+(?:로|으로)\s*결정)',
        r'(.+(?:확정|승인|선정).+)',
        r'(.+하기로\s*(?:함|했음|결정))',
    ]
    
    decisions = []
    for pattern in decision_patterns:
        for match in re.finditer(pattern, content, re.MULTILINE):
            decision = match.group(1).strip()
            if decision and decision not in decisions:
                decisions.append(decision)
    
    return decisions


def extract_action_items(content: str) -> list[dict[str, str | None]]:
    """
    Extract action items with dates and assignees.
    
    Looks for patterns like:
    - "담당: 문화국", "담당자: 김철수"
    - "~까지", "마감일:", "D-day"
    - "예정", "진행할 것"
    
    Args:
        content: Document content (typically result document)
        
    Returns:
        List of dicts with 'task', 'assignee', 'deadline' keys
    """
    action_items = []
    
    # Split by lines and look for action-related content
    lines = content.split('\n')
    
    current_item: dict[str, str | None] = {
        'task': None,
        'assignee': None,
        'deadline': None,
        'context': None,
    }
    
    for line in lines:
        line = line.strip()
        if not line:
            continue
        
        # Check for assignee patterns
        assignee_match = re.search(r'담당\s*(?:자)?[:：]\s*([가-힣]+(?:국|장)?)', line)
        if assignee_match:
            current_item['assignee'] = assignee_match.group(1)
        
        # Check for deadline patterns
        deadline_patterns = [
            r'(\d{1,2}[/\.]\d{1,2})',  # 4/20, 4.20
            r'(\d{1,2}월\s*\d{1,2}일)',  # 4월 20일
            r'(~\s*\d{1,2}[/\.]\d{1,2})',  # ~4/20
            r'(다음\s*주)',  # 다음 주
            r'(\d+월\s*(?:중|말|초))',  # 5월 중
        ]
        
        for pattern in deadline_patterns:
            deadline_match = re.search(pattern, line)
            if deadline_match:
                current_item['deadline'] = deadline_match.group(1)
                break
        
        # Check for task patterns (lines with action verbs)
        if any(keyword in line for keyword in ['예정', '진행', '완료', '준비', '작성', '제작', '확인']):
            if current_item.get('task') is None:
                current_item['task'] = line
            
            # If we have at least a task, add to list
            if current_item['task']:
                action_items.append(current_item.copy())
                current_item = {'task': None, 'assignee': None, 'deadline': None, 'context': None}
    
    return action_items


def build_placeholder_map(
    sections: list[DocumentSection],
    summaries: list[str],
) -> dict[str, str]:
    """
    Build placeholder replacement map for Smart Minutes.
    
    Maps agenda items to their summaries using naming convention:
    - {report_1_result} for 보고안건 1
    - {discuss_1_result} for 논의안건 1
    - {decision_1_result} for 의결안건 1
    - {other_1_result} for 기타안건 1
    
    Note: Uses single curly braces to match Google Docs template format.
    
    Args:
        sections: List of DocumentSections from split transcript
        summaries: List of summary strings (same order as sections)
        
    Returns:
        Dict mapping placeholders to summary text
        
    Example:
        >>> sections = [DocumentSection(title="논의안건 1. 컴씨 장소", ...)]
        >>> summaries = ["오크밸리로 결정"]
        >>> build_placeholder_map(sections, summaries)
        {'{discuss_1_result}': '오크밸리로 결정'}
    """
    replacements = {}
    
    # Track counts per agenda type for numbering
    type_counts = {'report': 0, 'discuss': 0, 'decision': 0, 'other': 0}
    
    for section, summary in zip(sections, summaries):
        agenda_type = section.agenda_type
        
        if agenda_type:
            # Use explicit number from title if available, otherwise increment
            num = section.agenda_number
            if num is None:
                type_counts[agenda_type] += 1
                num = type_counts[agenda_type]
            
            # Single curly braces to match Google Docs template format
            placeholder = f"{{{agenda_type}_{num}_result}}"
            replacements[placeholder] = summary
            
            logger.debug(
                "Created placeholder mapping",
                placeholder=placeholder,
                summary_preview=summary[:50] if summary else "",
            )
        else:
            # Generic placeholder for untyped sections
            placeholder = f"{{section_{len(replacements)+1}_result}}"
            replacements[placeholder] = summary
    
    logger.info(
        "Built placeholder map",
        total_replacements=len(replacements),
        placeholders=list(replacements.keys()),
    )
    
    return replacements


# Alias for backward compatibility with step_04_preprocess
def basic_cleanup(content: str) -> str:
    """Alias for normalize_whitespace for backward compatibility."""
    return normalize_whitespace(content)


def clean_markdown(text: str) -> str:
    """
    Clean markdown formatting from text for Google Docs insertion.
    
    Removes common markdown syntax that would appear as plain text
    in Google Docs:
    - Bold (**text** or __text__)
    - Italic (*text* or _text_)
    - Headers (# ## ###)
    - Bullet points (- or *)
    - Numbered lists
    - Code blocks (``` and ``)
    - Links [text](url)
    
    Args:
        text: Text potentially containing markdown
        
    Returns:
        Cleaned plain text suitable for Google Docs
        
    Example:
        >>> clean_markdown("**결정사항**: 오크밸리로 선정")
        '결정사항: 오크밸리로 선정'
    """
    if not text:
        return text
    
    # Preserve original for debugging
    original = text
    
    # Remove code blocks first (```...```)
    text = re.sub(r'```[\s\S]*?```', '', text)
    
    # Remove inline code (`code`)
    text = re.sub(r'`([^`]+)`', r'\1', text)
    
    # Remove bold (**text** or __text__)
    text = re.sub(r'\*\*([^*]+)\*\*', r'\1', text)
    text = re.sub(r'__([^_]+)__', r'\1', text)
    
    # Remove headers (# ## ###) at line start
    text = re.sub(r'^#{1,6}\s+', '', text, flags=re.MULTILINE)
    
    # IMPORTANT: Convert bullet points BEFORE italic removal
    # Otherwise `* item` gets captured by the italic regex first
    text = re.sub(r'^[\*\-]\s+', '• ', text, flags=re.MULTILINE)
    
    # Remove italic (*text* or _text_) - careful not to match **
    # This comes AFTER bullet conversion to avoid conflicts
    text = re.sub(r'(?<!\*)\*([^*]+)\*(?!\*)', r'\1', text)
    text = re.sub(r'(?<!_)_([^_]+)_(?!_)', r'\1', text)
    
    # Keep numbered lists but clean formatting
    text = re.sub(r'^(\d+)\.\s+', r'\1. ', text, flags=re.MULTILINE)
    
    # Remove links [text](url) -> text
    text = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', text)
    
    # Remove horizontal rules
    text = re.sub(r'^[\-\*_]{3,}$', '', text, flags=re.MULTILINE)
    
    # Clean up excessive whitespace
    text = re.sub(r'\n{3,}', '\n\n', text)
    text = text.strip()
    
    if text != original:
        logger.debug(
            "Cleaned markdown",
            original_len=len(original),
            cleaned_len=len(text),
        )
    
    return text


def clean_summary_for_docs(summary_result: dict) -> str:
    """
    Extract and clean summary from Gemini response for Google Docs.
    
    Takes the structured Gemini response and produces a clean text
    string suitable for insertion into Google Docs.
    
    Args:
        summary_result: Dict from GeminiService.summarize_agenda_section()
                       containing 'summary', 'decisions', 'action_items', etc.
        
    Returns:
        Formatted plain text for Google Docs
        
    Example:
        >>> result = {"summary": "**오크밸리**로 결정", "decisions": ["장소 확정"]}
        >>> clean_summary_for_docs(result)
        '오크밸리로 결정\n\n[결정사항]\n• 장소 확정'
    """
    parts = []
    
    # Main summary
    summary = summary_result.get("summary", "")
    if summary:
        parts.append(clean_markdown(summary))
    
    # Decisions
    decisions = summary_result.get("decisions", [])
    if decisions:
        parts.append("\n[결정사항]")
        for decision in decisions:
            parts.append(f"• {clean_markdown(decision)}")
    
    # Action items
    action_items = summary_result.get("action_items", [])
    if action_items:
        parts.append("\n[할 일]")
        for item in action_items:
            task = item.get("task", "")
            assignee = item.get("assignee", "")
            deadline = item.get("deadline", "")
            
            item_text = clean_markdown(task)
            if assignee:
                item_text += f" (담당: {assignee})"
            if deadline:
                item_text += f" (기한: {deadline})"
            parts.append(f"• {item_text}")
    
    # Discussion progress (if no decisions)
    if not decisions and summary_result.get("discussion_progress"):
        progress = summary_result.get("discussion_progress", "")
        parts.append(f"\n[논의 현황] {clean_markdown(progress)}")
    
    return "\n".join(parts)

