"""E2E Test Scenarios for Phase 2 Bug Fixes.

Tests:
1. Basic RAG chat with source retrieval
2. Multi-turn session context
3. year_filter and department_filter
4. drive_link URL validation
5. Error message sanitization
"""

import re
import sys

import requests

# Configuration
API_URL = "http://localhost:8000/api/v1/chat"
API_KEY = "debug"
HEADERS = {"Content-Type": "application/json", "X-API-Key": API_KEY}


def log(msg: str, status: str = "INFO") -> None:
    """Print formatted log message."""
    status_colors = {
        "PASS": "\033[92m",  # Green
        "FAIL": "\033[91m",  # Red
        "WARN": "\033[93m",  # Yellow
        "STEP": "\033[94m",  # Blue
        "INFO": "\033[0m",   # Default
    }
    color = status_colors.get(status, "\033[0m")
    reset = "\033[0m"
    print(f"{color}[{status}]{reset} {msg}")


def run_test() -> bool:
    """Run all E2E test scenarios."""
    session_id = None
    all_passed = True

    # ---------------------------------------------------------
    # Scenario 1: Basic Chat & Drive Link Validation
    # ---------------------------------------------------------
    log("Testing Basic Chat...", "STEP")
    payload = {"query": "2025년 일일호프 예산 알려줘"}
    try:
        res = requests.post(API_URL, json=payload, headers=HEADERS, timeout=60)
        res.raise_for_status()
        data = res.json()
        session_id = data.get("session_id")

        if not session_id:
            log("Session ID not returned", "FAIL")
            all_passed = False
            return all_passed

        # Check answer exists
        answer = data.get("answer", "")
        if answer:
            log(f"Answer received: {answer[:80]}...", "PASS")
        else:
            log("Empty answer received", "WARN")

        # Validate sources and drive_link
        sources = data.get("sources", [])
        if sources:
            log(f"Sources count: {len(sources)}", "INFO")
            for i, source in enumerate(sources):
                link = source.get("drive_link")
                if link:
                    # Validate drive_link format (20-60 char alphanumeric ID)
                    if re.search(r"docs\.google\.com/document/d/[a-zA-Z0-9_-]{20,}", link):
                        log(f"Source[{i}] Drive Link Valid: {link}", "PASS")
                    else:
                        log(f"Source[{i}] Invalid Drive Link: {link}", "FAIL")
                        all_passed = False
                else:
                    log(f"Source[{i}] No drive_link (drive_id may be invalid)", "INFO")
        else:
            log("No sources returned (may be expected if no matching docs)", "WARN")

        # Check metadata
        metadata = data.get("metadata", {})
        log(f"Latency: {metadata.get('latency_ms', 'N/A')}ms, "
            f"Retrieval: {metadata.get('retrieval_latency_ms', 'N/A')}ms, "
            f"Generation: {metadata.get('generation_latency_ms', 'N/A')}ms", "INFO")

        log(f"Basic Chat Success. Session ID: {session_id[:8]}...", "PASS")

    except requests.exceptions.RequestException as e:
        log(f"Basic Chat Failed: {e}", "FAIL")
        all_passed = False
        return all_passed

    # ---------------------------------------------------------
    # Scenario 2: Multi-turn Context
    # ---------------------------------------------------------
    log("Testing Multi-turn Context...", "STEP")
    payload = {
        "session_id": session_id,
        "query": "그거 언제 진행했어?"  # '그거' = 일일호프
    }
    try:
        res = requests.post(API_URL, json=payload, headers=HEADERS, timeout=60)
        res.raise_for_status()
        data = res.json()
        answer = data.get("answer", "")
        rewritten = data.get("rewritten_query")

        if rewritten:
            log(f"Query rewritten: '{rewritten[:50]}...'", "PASS")
        else:
            log("Query not rewritten (may still be valid)", "WARN")

        log(f"Multi-turn Response: {answer[:80]}...", "PASS")

    except requests.exceptions.RequestException as e:
        log(f"Multi-turn Failed: {e}", "FAIL")
        all_passed = False

    # ---------------------------------------------------------
    # Scenario 3: Filters (Year & Department)
    # ---------------------------------------------------------
    log("Testing Filters (year_filter=[2024], department_filter='문화국')...", "STEP")
    payload = {
        "session_id": session_id,
        "query": "작년 예산 내역 보여줘",
        "options": {
            "year_filter": [2024],  # Note: list type as per implementation
            "department_filter": "문화국"
        }
    }
    try:
        res = requests.post(API_URL, json=payload, headers=HEADERS, timeout=60)
        res.raise_for_status()
        data = res.json()
        answer = data.get("answer", "")
        sources = data.get("sources", [])

        log(f"Filter Request Success. Sources: {len(sources)}", "PASS")
        log(f"Answer: {answer[:80]}...", "INFO")
        log("Check server logs to verify SQL filter was applied", "WARN")

    except requests.exceptions.RequestException as e:
        log(f"Filter Request Failed: {e}", "FAIL")
        all_passed = False

    # ---------------------------------------------------------
    # Scenario 4: Error Message Sanitization
    # ---------------------------------------------------------
    log("Testing Error Message Sanitization...", "STEP")
    # Send invalid user_level to trigger validation error
    payload = {
        "query": "테스트",
        "user_level": 999  # Invalid: should be 1-4
    }
    try:
        res = requests.post(API_URL, json=payload, headers=HEADERS, timeout=30)

        if res.status_code == 422:
            # Pydantic validation error - expected
            log("Validation error returned (422) - Expected behavior", "PASS")
        elif res.status_code == 500:
            detail = res.json().get("detail", "")
            # Check that internal details are NOT exposed
            if "Chat processing failed. Please try again later." in detail:
                log("Error message properly sanitized", "PASS")
            elif any(x in detail.lower() for x in ["traceback", "sql", "connection", "password"]):
                log(f"SECURITY: Internal details exposed: {detail}", "FAIL")
                all_passed = False
            else:
                log(f"500 error with message: {detail}", "WARN")
        else:
            log(f"Unexpected status code: {res.status_code}", "WARN")

    except requests.exceptions.RequestException as e:
        log(f"Error test request failed: {e}", "FAIL")

    # ---------------------------------------------------------
    # Summary
    # ---------------------------------------------------------
    print("\n" + "=" * 50)
    if all_passed:
        log("All E2E tests passed!", "PASS")
    else:
        log("Some tests failed. Check logs above.", "FAIL")
    print("=" * 50)

    return all_passed


if __name__ == "__main__":
    success = run_test()
    sys.exit(0 if success else 1)
