"""Standalone test script for Step 4 preprocessing without DB dependencies.

Run directly: python -m tests.test_pipeline.test_step4_standalone
"""

import asyncio
import sys
from pathlib import Path

# Add backend to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app.pipeline.step_04_preprocess import PreprocessingService


async def test_basic_preprocessing():
    """Test basic preprocessing with sample content."""
    sample_content = """| 안건 | <보고안건> 1. 활동보고 2. 예산 집행 현황 <논의안건> 1. 예산안 심의 2. 행사 기획 <기타안건> 1. 자유 질의 |
| --- | --- |

보고안건 1 활동보고
담당자: 김철수

이번 학기 활동 내용을 보고합니다.
- 신입생 환영회 진행
- 학술제 개최

보고안건 2 예산 집행 현황
담당자: 이영희

현재까지 예산 집행률은 60%입니다.

논의안건 1 예산안 심의
담당자: 박민수

2024년 2학기 예산안을 심의합니다.
총 예산: 500만원

논의안건 2 행사 기획
담당자: 최지훈

축제 행사를 기획합니다.

기타안건 1 자유 질의
담당자: 전체

자유롭게 질의응답 시간을 갖습니다.
"""

    print("=" * 80)
    print("Step 4 Preprocessing Test")
    print("=" * 80)
    print(f"\n📄 Original content length: {len(sample_content)} characters\n")

    preprocessor = PreprocessingService()
    result = await preprocessor.preprocess_document(
        sample_content,
        is_meeting_document=True,
    )

    print("✅ Preprocessing completed!")
    print(f"   Headers found: {len(result.headers_found)}")
    print(f"   Sections count: {result.sections_count}")
    print(f"   Processed content length: {len(result.processed_content)} characters")
    print(f"   Content preserved: {len(result.processed_content) / len(sample_content) * 100:.1f}%")

    print("\n📋 Headers found:")
    for i, header in enumerate(result.headers_found, 1):
        print(f"   {i}. {header}")

    print("\n📝 Processed content preview (first 800 chars):")
    print("-" * 80)
    print(result.processed_content[:800])
    print("-" * 80)

    # Save to debug_output
    debug_dir = Path(__file__).parent.parent / "debug_output"
    debug_dir.mkdir(parents=True, exist_ok=True)
    
    output_path = debug_dir / "04_structured_standalone.md"
    output_path.write_text(result.processed_content, encoding="utf-8")
    print(f"\n💾 Full output saved to: {output_path}")

    # Assertions
    assert result.processed_content is not None
    assert len(result.processed_content) > 0
    assert len(result.headers_found) > 0, "Should have found headers"
    
    # Check content preservation (at least 70%)
    preservation_ratio = len(result.processed_content) / len(sample_content)
    assert preservation_ratio >= 0.7, f"Content significantly reduced: {preservation_ratio*100:.1f}%"

    print("\n✅ All assertions passed!")


async def test_html_residue_content():
    """Test with content containing HTML tags."""
    sample_with_html = """| 안건 | <보고안건> 1. 활동보고 |
| --- | --- |

<table><thead></thead><tbody><tr><td>보고안건 1</td><td>활동보고</td></tr></tbody></table>

담당자: 김철수

# 이것은 파서가 임의로 생성한 헤더입니다

활동 내용을 보고합니다.

## 또 다른 임의 헤더

세부 내용입니다.
"""

    print("\n" + "=" * 80)
    print("HTML Residue Test")
    print("=" * 80)
    print(f"\n📄 Input has HTML: {'<table>' in sample_with_html}")
    print(f"   Input has arbitrary headers: {'#' in sample_with_html}\n")

    preprocessor = PreprocessingService()
    result = await preprocessor.preprocess_document(
        sample_with_html,
        is_meeting_document=True,
    )

    print("✅ Preprocessing completed!")
    print(f"   Headers found: {len(result.headers_found)}")
    
    print("\n📝 Processed content:")
    print("-" * 80)
    print(result.processed_content)
    print("-" * 80)

    # Save output
    debug_dir = Path(__file__).parent.parent / "debug_output"
    output_path = debug_dir / "04_structured_with_html.md"
    output_path.write_text(result.processed_content, encoding="utf-8")
    print(f"\n💾 Output saved to: {output_path}")


async def main():
    """Run all tests."""
    try:
        await test_basic_preprocessing()
        await test_html_residue_content()
        print("\n" + "=" * 80)
        print("🎉 All tests passed successfully!")
        print("=" * 80)
    except Exception as e:
        print(f"\n❌ Test failed with error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
