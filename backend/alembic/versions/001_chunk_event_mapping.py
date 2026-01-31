"""Add chunk-level event mapping and chat logs table

Revision ID: 001_chunk_event_mapping
Revises: 
Create Date: 2026-01-31
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "001_chunk_event_mapping"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """
    Schema changes per implementation plan:
    1. documents.event_id - Already nullable, add explicit nullable constraint
    2. document_chunks.related_event_id - NEW: Chunk-level event mapping
    3. document_chunks.inferred_event_title - NEW: LLM-inferred event name
    4. chat_logs table - NEW: Conversation history storage
    """
    
    # 1. Add related_event_id to document_chunks (Chunk-level Event mapping)
    op.add_column(
        "document_chunks",
        sa.Column(
            "related_event_id",
            sa.Integer(),
            sa.ForeignKey("events.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_document_chunks_related_event_id",
        "document_chunks",
        ["related_event_id"],
    )

    # 2. Add inferred_event_title to document_chunks
    op.add_column(
        "document_chunks",
        sa.Column("inferred_event_title", sa.String(500), nullable=True),
    )

    # 3. Create chat_logs table
    op.create_table(
        "chat_logs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("session_id", sa.String(100), nullable=False, index=True),
        sa.Column("user_level", sa.Integer(), default=4, index=True),
        sa.Column("user_query", sa.Text(), nullable=False),
        sa.Column("rewritten_query", sa.Text(), nullable=True),
        sa.Column("ai_response", sa.Text(), nullable=False),
        sa.Column(
            "retrieved_chunks",
            postgresql.JSONB(astext_type=sa.Text()),
            default=[],
        ),
        sa.Column(
            "sources",
            postgresql.JSONB(astext_type=sa.Text()),
            default=[],
        ),
        sa.Column("turn_index", sa.Integer(), default=0, index=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("retrieval_latency_ms", sa.Integer(), nullable=True),
        sa.Column("generation_latency_ms", sa.Integer(), nullable=True),
        sa.Column(
            "request_metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            default={},
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
        ),
    )

    # 4. Create index on chat_logs for session queries
    op.create_index(
        "ix_chat_logs_session_turn",
        "chat_logs",
        ["session_id", "turn_index"],
    )


def downgrade() -> None:
    """Reverse the migrations."""
    
    # Drop chat_logs table
    op.drop_index("ix_chat_logs_session_turn", table_name="chat_logs")
    op.drop_table("chat_logs")

    # Remove document_chunks columns
    op.drop_column("document_chunks", "inferred_event_title")
    op.drop_index("ix_document_chunks_related_event_id", table_name="document_chunks")
    op.drop_column("document_chunks", "related_event_id")
