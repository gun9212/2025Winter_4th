#!/usr/bin/env python3
"""Interactive Chat Client - Test RAG chatbot in terminal.

Usage:
    python -m scripts.interactive_chat
    python -m scripts.interactive_chat --url http://localhost:8000
    python -m scripts.interactive_chat --session my-session-id
"""

import argparse
import sys
from uuid import uuid4

import requests

# Try to import rich for colorful output
try:
    from rich.console import Console
    from rich.markdown import Markdown
    from rich.panel import Panel
    from rich.table import Table
    RICH_AVAILABLE = True
    console = Console()
except ImportError:
    RICH_AVAILABLE = False
    console = None


# Configuration
DEFAULT_API_URL = "http://localhost:8000/api/v1/chat"
DEFAULT_API_KEY = "debug"


def print_header():
    """Print welcome header."""
    header = """
╔═══════════════════════════════════════════════════════════╗
║           Council-AI Interactive Chat Client              ║
║                                                           ║
║  Commands:                                                ║
║    exit, quit, q  - Exit the chat                         ║
║    clear, reset   - Start new session                     ║
║    help, ?        - Show this help                        ║
╚═══════════════════════════════════════════════════════════╝
"""
    if RICH_AVAILABLE:
        console.print(header, style="bold cyan")
    else:
        print(header)


def print_answer(answer: str, sources: list, metadata: dict):
    """Print the AI answer and sources."""
    if RICH_AVAILABLE:
        # Print answer with markdown rendering
        console.print("\n[bold green]🤖 AI 답변:[/bold green]")
        console.print(Panel(Markdown(answer), border_style="green"))

        # Print sources if available
        if sources:
            table = Table(title="📚 참고 문서", show_header=True, header_style="bold magenta")
            table.add_column("문서명", style="cyan")
            table.add_column("섹션", style="yellow")
            table.add_column("관련도", justify="right", style="green")
            table.add_column("링크", style="blue")

            for src in sources:
                table.add_row(
                    src.get("document_title", "Unknown")[:40],
                    (src.get("section_header") or "-")[:30],
                    f"{src.get('relevance_score', 0):.2%}",
                    "🔗" if src.get("drive_link") else "-"
                )

            console.print(table)

        # Print metadata
        console.print(
            f"\n[dim]⏱️ 응답시간: {metadata.get('latency_ms', 0)}ms | "
            f"검색: {metadata.get('retrieval_latency_ms', 0)}ms | "
            f"생성: {metadata.get('generation_latency_ms', 0)}ms[/dim]"
        )
    else:
        # Plain text output
        print("\n🤖 AI 답변:")
        print("-" * 50)
        print(answer)
        print("-" * 50)

        if sources:
            print("\n📚 참고 문서:")
            for i, src in enumerate(sources, 1):
                print(f"  {i}. {src.get('document_title', 'Unknown')}")
                if src.get("section_header"):
                    print(f"     섹션: {src['section_header']}")
                print(f"     관련도: {src.get('relevance_score', 0):.2%}")

        print(f"\n⏱️ 응답시간: {metadata.get('latency_ms', 0)}ms")


def print_error(message: str):
    """Print error message."""
    if RICH_AVAILABLE:
        console.print(f"[bold red]❌ 오류:[/bold red] {message}")
    else:
        print(f"❌ 오류: {message}")


def print_info(message: str):
    """Print info message."""
    if RICH_AVAILABLE:
        console.print(f"[bold blue]ℹ️[/bold blue] {message}")
    else:
        print(f"ℹ️ {message}")


def send_chat_request(
    api_url: str,
    api_key: str,
    query: str,
    session_id: str,
    user_level: int = 1,
) -> dict | None:
    """Send chat request to API."""
    headers = {
        "Content-Type": "application/json",
        "X-API-Key": api_key,
    }

    payload = {
        "query": query,
        "session_id": session_id,
        "user_level": user_level,
        "options": {
            "include_sources": True,
            "max_results": 5,
        }
    }

    try:
        response = requests.post(
            api_url,
            json=payload,
            headers=headers,
            timeout=120,  # 2 minutes timeout
        )

        if response.status_code == 200:
            return response.json()
        else:
            error_detail = response.json().get("detail", response.text)
            print_error(f"API 응답 오류 ({response.status_code}): {error_detail}")
            return None

    except requests.exceptions.ConnectionError:
        print_error("서버에 연결할 수 없습니다. 서버가 실행 중인지 확인하세요.")
        print_info("서버 시작: docker compose up -d backend")
        return None
    except requests.exceptions.Timeout:
        print_error("요청 시간이 초과되었습니다.")
        return None
    except Exception as e:
        print_error(f"요청 실패: {str(e)}")
        return None


def main():
    parser = argparse.ArgumentParser(description="Interactive Chat Client")
    parser.add_argument(
        "--url",
        default=DEFAULT_API_URL,
        help=f"API endpoint URL (default: {DEFAULT_API_URL})",
    )
    parser.add_argument(
        "--api-key",
        default=DEFAULT_API_KEY,
        help=f"API key for authentication (default: {DEFAULT_API_KEY})",
    )
    parser.add_argument(
        "--session",
        default=None,
        help="Session ID for conversation continuity (default: auto-generated)",
    )
    parser.add_argument(
        "--user-level",
        type=int,
        default=4,
        choices=[1, 2, 3, 4],
        help="User access level: 1=회장단, 2=국장단, 3=국원, 4=일반 (default: 4)",
    )
    args = parser.parse_args()

    # Generate session ID if not provided
    session_id = args.session or f"interactive-{uuid4().hex[:8]}"

    # Print header
    print_header()
    print_info(f"API URL: {args.url}")
    print_info(f"Session ID: {session_id}")
    print_info(f"User Level: {args.user_level}")

    if RICH_AVAILABLE:
        console.print("[dim]rich 라이브러리 사용 중 (컬러 출력 활성화)[/dim]\n")
    else:
        print("(rich 라이브러리 없음 - 기본 출력 모드)\n")

    # Main chat loop
    while True:
        try:
            # Get user input
            if RICH_AVAILABLE:
                query = console.input("[bold yellow]질문 입력 >[/bold yellow] ")
            else:
                query = input("질문 입력 > ")

            # Strip whitespace
            query = query.strip()

            # Check for empty input
            if not query:
                continue

            # Check for exit commands
            if query.lower() in ("exit", "quit", "q", "종료"):
                print_info("채팅을 종료합니다. 안녕히 가세요! 👋")
                break

            # Check for reset commands
            if query.lower() in ("clear", "reset", "새로고침"):
                session_id = f"interactive-{uuid4().hex[:8]}"
                print_info(f"새 세션 시작: {session_id}")
                continue

            # Check for help commands
            if query.lower() in ("help", "?", "도움말"):
                print_header()
                continue

            # Send request
            if RICH_AVAILABLE:
                with console.status("[bold green]생각 중...[/bold green]"):
                    result = send_chat_request(
                        api_url=args.url,
                        api_key=args.api_key,
                        query=query,
                        session_id=session_id,
                        user_level=args.user_level,
                    )
            else:
                print("⏳ 응답 대기 중...")
                result = send_chat_request(
                    api_url=args.url,
                    api_key=args.api_key,
                    query=query,
                    session_id=session_id,
                    user_level=args.user_level,
                )

            # Print result
            if result:
                print_answer(
                    answer=result.get("answer", "응답 없음"),
                    sources=result.get("sources", []),
                    metadata=result.get("metadata", {}),
                )

                # Show rewritten query if different
                rewritten = result.get("rewritten_query")
                if rewritten and rewritten != query:
                    if RICH_AVAILABLE:
                        console.print(f"\n[dim]🔄 쿼리 재작성: {rewritten}[/dim]")
                    else:
                        print(f"\n🔄 쿼리 재작성: {rewritten}")

            print()  # Empty line for readability

        except KeyboardInterrupt:
            print("\n")
            print_info("Ctrl+C 감지. 종료합니다. 👋")
            break
        except EOFError:
            print("\n")
            print_info("입력 종료. 안녕히 가세요! 👋")
            break


if __name__ == "__main__":
    main()
