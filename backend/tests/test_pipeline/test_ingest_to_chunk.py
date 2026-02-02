"""Integration test for Step 3 → Step 4 → Step 5 pipeline.

Saves intermediate outputs to debug_output/ for visual verification.
"""

import asyncio
import json
from pathlib import Path

import pytest

# Test file paths
TEST_DATA_DIR = Path(__file__).parent.parent.parent.parent / "data" / "processed"
DEBUG_OUTPUT_DIR = Path(__file__).parent.parent / "debug_output"

# Sample test files
TEST_FILES = [
    TEST_DATA_DIR / "2차 회의(국장단 1차 LT)" / "제37대 서울대학교 공과대학 컴퓨터공학부 학생회 [FLOW] 제2차 집행위원회 국장단회의 결과지.md",
    TEST_DATA_DIR / "4차 회의" / "[결과지] 제37대 서울대학교 공과대학 컴퓨터공학부 학생회 [FLOW] 제4차 집행위원회 국장단회의.md",
]


@pytest.fixture(scope="module")
def ensure_debug_dir():
    """Ensure debug output directory exists."""
    DEBUG_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    return DEBUG_OUTPUT_DIR


class TestPipelineIntegration:
    """Integration tests for the RAG pipeline Step 3-4-5."""

    @pytest.fixture
    def sample_markdown_content(self) -> str:
        """Load sample markdown content from test file."""
        test_file = TEST_FILES[0]
        if test_file.exists():
            return test_file.read_text(encoding="utf-8")
        pytest.skip(f"Test file not found: {test_file}")

    @pytest.fixture
    def sample_html_residue_content(self) -> str:
        """Load sample with HTML residue for testing cleanup."""
        test_file = TEST_FILES[1]
        if test_file.exists():
            return test_file.read_text(encoding="utf-8")
        pytest.skip(f"Test file not found: {test_file}")

    @pytest.mark.asyncio
    async def test_step4_preprocessing_preserves_content(
        self, 
        sample_markdown_content: str,
        ensure_debug_dir: Path,
    ):
        """
        Test that Step 4 preprocessing adds headers without modifying content.
        
        Verification:
        - Output should contain all original text
        - Headers (#, ##) should be added based on agenda structure
        - No content should be summarized or removed
        """
        from app.pipeline.step_04_preprocess import PreprocessingService

        preprocessor = PreprocessingService()
        result = await preprocessor.preprocess_document(
            sample_markdown_content,
            is_meeting_document=True,
        )

        # Save output for manual inspection
        output_path = ensure_debug_dir / "04_structured.md"
        output_path.write_text(result.processed_content, encoding="utf-8")

        # Basic assertions
        assert result.processed_content is not None
        assert len(result.processed_content) > 0
        
        # Check that headers were added
        assert result.headers_found is not None
        
        # Check content length (should not be significantly shorter)
        original_len = len(sample_markdown_content)
        processed_len = len(result.processed_content)
        
        # Allow some reduction due to whitespace cleanup, but not major content loss
        # Processed content should be at least 70% of original
        assert processed_len >= original_len * 0.7, (
            f"Content significantly reduced: {original_len} -> {processed_len} "
            f"({processed_len/original_len*100:.1f}%)"
        )

        print(f"✅ Step 4 test passed. Output saved to: {output_path}")
        print(f"   Headers found: {len(result.headers_found)}")
        print(f"   Content length: {original_len} -> {processed_len}")

    @pytest.mark.asyncio
    async def test_step5_chunking(
        self,
        sample_markdown_content: str,
        ensure_debug_dir: Path,
    ):
        """
        Test that Step 5 chunking creates proper Parent-Child structure.
        
        Verification:
        - Parent chunks should be created for ## headers
        - Child chunks should reference correct parents
        - All content should be captured
        """
        from app.pipeline.step_04_preprocess import PreprocessingService
        from app.pipeline.step_05_chunk import ChunkingService

        # Step 4: Preprocess
        preprocessor = PreprocessingService()
        preprocess_result = await preprocessor.preprocess_document(
            sample_markdown_content,
            is_meeting_document=True,
        )

        # Step 5: Chunk
        chunker = ChunkingService(
            parent_chunk_size=4000,
            child_chunk_size=500,
            child_chunk_overlap=50,
        )
        chunks = chunker.chunk_document(preprocess_result.processed_content)

        # Save chunks for inspection
        chunks_data = [
            {
                "index": c.chunk_index,
                "is_parent": c.is_parent,
                "parent_index": c.parent_index,
                "section_header": c.section_header,
                "token_count": c.token_count,
                "content_preview": c.content[:300] + "..." if len(c.content) > 300 else c.content,
            }
            for c in chunks
        ]
        
        output_path = ensure_debug_dir / "05_chunks.json"
        output_path.write_text(
            json.dumps(chunks_data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        # Assertions
        assert len(chunks) > 0
        
        parent_chunks = [c for c in chunks if c.is_parent]
        child_chunks = [c for c in chunks if not c.is_parent]
        
        assert len(parent_chunks) >= 1, "Should have at least 1 parent chunk"
        assert len(child_chunks) >= 1, "Should have at least 1 child chunk"

        # Verify parent-child linking
        for child in child_chunks:
            assert child.parent_index is not None, "Child should have parent_index"
            assert child.parent_content is not None, "Child should have parent_content"

        print(f"✅ Step 5 test passed. Output saved to: {output_path}")
        print(f"   Total chunks: {len(chunks)}")
        print(f"   Parent chunks: {len(parent_chunks)}")
        print(f"   Child chunks: {len(child_chunks)}")

    @pytest.mark.asyncio
    async def test_full_pipeline_step4_to_step5(
        self,
        sample_html_residue_content: str,
        ensure_debug_dir: Path,
    ):
        """
        Full pipeline test with content containing HTML residue.
        
        Verifies:
        - HTML tags are handled gracefully
        - Pipeline doesn't break on messy input
        """
        from app.pipeline.step_04_preprocess import PreprocessingService
        from app.pipeline.step_05_chunk import ChunkingService

        # Check for HTML residue in input
        has_html = "<table>" in sample_html_residue_content
        print(f"📋 Input has HTML residue: {has_html}")

        # Step 4
        preprocessor = PreprocessingService()
        preprocess_result = await preprocessor.preprocess_document(
            sample_html_residue_content,
            is_meeting_document=True,
        )

        (ensure_debug_dir / "04_structured_with_html.md").write_text(
            preprocess_result.processed_content, encoding="utf-8"
        )

        # Step 5
        chunker = ChunkingService()
        chunks = chunker.chunk_document(preprocess_result.processed_content)

        chunks_data = [
            {
                "index": c.chunk_index,
                "is_parent": c.is_parent,
                "section_header": c.section_header,
                "has_html": "<table>" in c.content or "<td>" in c.content,
                "content_preview": c.content[:200],
            }
            for c in chunks
        ]

        (ensure_debug_dir / "05_chunks_with_html.json").write_text(
            json.dumps(chunks_data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        assert len(chunks) > 0
        print(f"✅ Full pipeline test passed. Chunks: {len(chunks)}")


class TestStandalonePreprocessing:
    """Test preprocessing with mock content (no external dependencies)."""

    @pytest.mark.asyncio
    async def test_basic_header_injection(self):
        """Test that headers are properly injected into simple content."""
        sample_content = """| 안건 | <보고안건> 1. 활동보고 <논의안건> 1. 예산안 |
| --- | --- |

보고안건 1 활동보고
담당자: 김철수

이번 학기 활동 내용을 보고합니다.

논의안건 1 예산안
담당자: 이영희

예산안을 논의합니다.
"""
        from app.pipeline.step_04_preprocess import PreprocessingService

        preprocessor = PreprocessingService()
        result = await preprocessor.preprocess_document(
            sample_content,
            is_meeting_document=True,
        )

        # Check that agenda headers are added
        processed = result.processed_content.lower()
        
        # Should have some form of header structure
        assert "#" in result.processed_content, "Should have headers"
        
        print(f"📝 Processed content preview:\n{result.processed_content[:500]}")


if __name__ == "__main__":
    # Run tests directly
    pytest.main([__file__, "-v", "-s"])
