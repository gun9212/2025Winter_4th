"""Unit tests for Parent-Child chunking (Step 5)."""

import pytest

from app.pipeline.step_05_chunk import ChunkingService, ChunkData


@pytest.fixture
def chunker():
    """Create chunking service with test settings."""
    return ChunkingService(
        parent_chunk_size=4000,
        child_chunk_size=200,  # Smaller for testing
        child_chunk_overlap=20,
    )


class TestParentChildChunking:
    """Tests for Parent-Child chunking strategy."""

    def test_basic_parent_child_split(self, chunker):
        """Test basic splitting into parent and child chunks."""
        content = """# 보고안건

## 1. 축제 준비 현황 보고

축제 준비가 순조롭게 진행되고 있습니다.
현재까지 진행된 사항:
- 장소 대관 완료
- 가수 섭외 진행 중
- 부스 신청 접수 중

예산 집행률은 30%입니다.

## 2. 학생회비 납부 현황

2학기 학생회비 납부율이 작년 대비 5% 증가했습니다.
총 납부 인원: 350명
"""
        
        chunks = chunker.chunk_document(content)
        
        # Should have parent chunks for each ## header
        parent_chunks = [c for c in chunks if c.is_parent]
        child_chunks = [c for c in chunks if not c.is_parent]
        
        assert len(parent_chunks) >= 2  # At least 2 agenda items
        assert len(child_chunks) >= len(parent_chunks)  # At least 1 child per parent

    def test_child_has_parent_content(self, chunker):
        """Test that child chunks store full parent content."""
        content = """## 테스트 안건

이것은 테스트 안건의 첫 번째 문단입니다.
내용이 길어지면 여러 개의 child chunk로 분할됩니다.

이것은 두 번째 문단입니다.
"""
        
        chunks = chunker.chunk_document(content)
        child_chunks = [c for c in chunks if not c.is_parent]
        
        for child in child_chunks:
            # Each child should have parent_content
            assert child.parent_content is not None
            assert len(child.parent_content) >= len(child.content)

    def test_section_header_extraction(self, chunker):
        """Test section header extraction from chunks."""
        content = """## 논의안건 1. 축제 가수 섭외 건

논의 내용입니다.
"""
        
        chunks = chunker.chunk_document(content)
        parent_chunk = next((c for c in chunks if c.is_parent), None)
        
        assert parent_chunk is not None
        assert parent_chunk.section_header is not None
        assert "축제 가수" in parent_chunk.section_header

    def test_chunk_index_ordering(self, chunker):
        """Test that chunks have correct index ordering."""
        content = """## 안건 1

내용 1

## 안건 2

내용 2
"""
        
        chunks = chunker.chunk_document(content)
        
        # Indices should be sequential
        indices = [c.chunk_index for c in chunks]
        assert indices == sorted(indices)
        assert len(set(indices)) == len(indices)  # All unique

    def test_parent_index_linking(self, chunker):
        """Test that child chunks are linked to correct parent."""
        content = """## 안건 1

긴 내용입니다. """ * 20 + """

## 안건 2

다른 긴 내용입니다. """ * 20
        
        chunks = chunker.chunk_document(content)
        
        parent_chunks = [c for c in chunks if c.is_parent]
        child_chunks = [c for c in chunks if not c.is_parent]
        
        for child in child_chunks:
            # Each child should have a valid parent index
            assert child.parent_index is not None
            # Parent index should reference an actual parent
            assert any(p.chunk_index == child.parent_index for p in parent_chunks)


class TestChunkGrouping:
    """Tests for chunk grouping utilities."""

    def test_get_parent_chunks(self, chunker):
        """Test filtering parent chunks."""
        content = """## 안건 1
내용
"""
        chunks = chunker.chunk_document(content)
        parents = chunker.get_parent_chunks(chunks)
        
        assert all(c.is_parent for c in parents)

    def test_get_child_chunks(self, chunker):
        """Test filtering child chunks."""
        content = """## 안건 1
내용
"""
        chunks = chunker.chunk_document(content)
        children = chunker.get_child_chunks(chunks)
        
        assert all(not c.is_parent for c in children)

    def test_group_by_parent(self, chunker):
        """Test grouping children by parent index."""
        content = """## 안건 1

첫 번째 안건 내용입니다. 여러 문장으로 구성됩니다.

## 안건 2

두 번째 안건 내용입니다. 역시 여러 문장입니다.
"""
        
        chunks = chunker.chunk_document(content)
        groups = chunker.group_by_parent(chunks)
        
        # Should have groups for each parent
        assert len(groups) >= 1
        
        for parent_idx, children in groups.items():
            assert all(c.parent_index == parent_idx for c in children)
