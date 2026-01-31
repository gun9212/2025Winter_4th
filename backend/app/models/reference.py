"""Reference model for storing sensitive file links without embedding content."""

from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.event import Event


class Reference(Base, TimestampMixin):
    """
    Reference model for storing links to sensitive files.
    
    These files contain personal information (PII) and should NOT be
    embedded into the vector database. Instead, only metadata and
    secure links are stored for retrieval.
    
    Examples:
        - Google Forms for event registration
        - Student fee payment spreadsheets
        - Participant name lists
    """

    __tablename__ = "references"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    # Event association
    event_id: Mapped[int | None] = mapped_column(
        ForeignKey("events.id", ondelete="SET NULL"),
        index=True,
    )

    # Reference information
    description: Mapped[str] = mapped_column(Text, nullable=False)
    file_link: Mapped[str] = mapped_column(Text, nullable=False)
    file_type: Mapped[str | None] = mapped_column(String(50))  # gform, gsheet, etc.
    file_name: Mapped[str | None] = mapped_column(String(500))
    
    # Access level (matching document authority_level)
    # 1: 회장단만, 2: 국장단까지, 3: 모든 국원, 4: 일반 대중
    access_level: Mapped[int] = mapped_column(default=3)

    # Additional metadata
    metadata: Mapped[dict | None] = mapped_column(JSONB, default=dict)

    # Relationships
    event: Mapped["Event"] = relationship("Event", back_populates="references")

    def __repr__(self) -> str:
        return f"<Reference(id={self.id}, description='{self.description[:30]}...', type={self.file_type})>"
