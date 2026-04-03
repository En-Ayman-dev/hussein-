from sqlalchemy import Column, Integer, String, Text, JSON, ForeignKey, Enum
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import JSONB
from pgvector.sqlalchemy import Vector
from typing import List, Optional
import enum

EMBEDDING_DIMENSIONS = 1536


class Base(DeclarativeBase):
    """Base class for all SQLAlchemy models."""
    pass


class RelationType(enum.Enum):
    """Enumeration of concept relation types."""
    CAUSES = "causes"
    OPPOSES = "opposes"
    ESTABLISHES = "establishes"
    IS_MEANS_FOR = "isMeansFor"
    RELATED_TO = "relatedTo"
    NEGATES = "negates"
    IS_CONDITION_FOR = "isConditionFor"
    IS_CAUSED_BY = "isCausedBy"
    PRECEDES = "precedes"
    BELONGS_TO_GROUP = "belongsToGroup"
    BELONGS_TO_LESSON = "belongsToLesson"
    BELONGS_TO_COLLECTION = "belongsToCollection"


class Concept(Base):
    """Model representing an ontology concept."""
    __tablename__ = "concepts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    uri: Mapped[str] = mapped_column(String(500), unique=True, nullable=False, index=True)
    labels: Mapped[Optional[List[str]]] = mapped_column(JSONB, nullable=True)
    definition: Mapped[Optional[List[str]]] = mapped_column(JSONB, nullable=True)
    quote: Mapped[Optional[List[str]]] = mapped_column(JSONB, nullable=True)
    actions: Mapped[Optional[List[str]]] = mapped_column(JSONB, nullable=True)
    importance: Mapped[Optional[List[str]]] = mapped_column(JSONB, nullable=True)

    # pgvector embedding column. Must stay aligned with the embedding service config.
    embedding: Mapped[Optional[List[float]]] = mapped_column(Vector(EMBEDDING_DIMENSIONS), nullable=True)

    # Relationships
    synonyms: Mapped[List["ConceptSynonym"]] = relationship(
        "ConceptSynonym",
        back_populates="concept",
        cascade="all, delete-orphan"
    )
    outgoing_relations: Mapped[List["ConceptRelation"]] = relationship(
        "ConceptRelation",
        back_populates="source_concept",
        cascade="all, delete-orphan",
        foreign_keys="ConceptRelation.source_concept_id"
    )
    incoming_relations: Mapped[List["ConceptRelation"]] = relationship(
        "ConceptRelation",
        back_populates="target_concept",
        cascade="all, delete-orphan",
        foreign_keys="ConceptRelation.target_concept_id"
    )

    def __repr__(self) -> str:
        return f"<Concept(id={self.id}, uri='{self.uri}')>"


class ConceptSynonym(Base):
    """Model representing concept synonyms."""
    __tablename__ = "concept_synonyms"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    subject_uri: Mapped[str] = mapped_column(String(500), nullable=False, index=True)
    predicate: Mapped[str] = mapped_column(String(200), nullable=False)
    object_value: Mapped[str] = mapped_column(Text, nullable=False)

    # pgvector embedding column for synonym search
    embedding: Mapped[Optional[List[float]]] = mapped_column(Vector(EMBEDDING_DIMENSIONS), nullable=True)

    # Foreign key relationship to concept (optional, for when subject_uri matches a concept)
    concept_id: Mapped[Optional[int]] = mapped_column(
        Integer,
        ForeignKey("concepts.id"),
        nullable=True
    )

    # Relationship
    concept: Mapped[Optional["Concept"]] = relationship("Concept", back_populates="synonyms")

    def __repr__(self) -> str:
        return f"<ConceptSynonym(id={self.id}, subject='{self.subject_uri}', object='{self.object_value[:50]}...')>"


class ConceptRelation(Base):
    """Model representing relationships between concepts."""
    __tablename__ = "concept_relations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    type: Mapped[RelationType] = mapped_column(Enum(RelationType), nullable=False, index=True)
    source_uri: Mapped[str] = mapped_column(String(500), nullable=False, index=True)
    target_uri: Mapped[str] = mapped_column(String(500), nullable=False, index=True)

    # pgvector embedding column for relation context
    embedding: Mapped[Optional[List[float]]] = mapped_column(Vector(EMBEDDING_DIMENSIONS), nullable=True)

    # Foreign key relationships to concepts (optional, for when URIs match concepts)
    source_concept_id: Mapped[Optional[int]] = mapped_column(
        Integer,
        ForeignKey("concepts.id"),
        nullable=True
    )
    target_concept_id: Mapped[Optional[int]] = mapped_column(
        Integer,
        ForeignKey("concepts.id"),
        nullable=True
    )

    # Relationships
    source_concept: Mapped[Optional["Concept"]] = relationship(
        "Concept",
        back_populates="outgoing_relations",
        foreign_keys=[source_concept_id]
    )
    target_concept: Mapped[Optional["Concept"]] = relationship(
        "Concept",
        back_populates="incoming_relations",
        foreign_keys=[target_concept_id]
    )

    def __repr__(self) -> str:
        return f"<ConceptRelation(id={self.id}, type={self.type.value}, source='{self.source_uri}', target='{self.target_uri}')>"


class Document(Base):
    """Model representing documents that reference concepts."""
    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    content: Mapped[Text] = mapped_column(Text, nullable=False)

    # Metadata as JSONB for flexibility
    doc_metadata: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)

    # pgvector embedding column for document search
    embedding: Mapped[Optional[List[float]]] = mapped_column(Vector(EMBEDDING_DIMENSIONS), nullable=True)

    # Optional foreign key to link document to a primary concept
    primary_concept_id: Mapped[Optional[int]] = mapped_column(
        Integer,
        ForeignKey("concepts.id"),
        nullable=True
    )

    # Relationship
    primary_concept: Mapped[Optional["Concept"]] = relationship("Concept")

    def __repr__(self) -> str:
        return f"<Document(id={self.id}, title='{self.title[:50]}...')>"


# Database setup helper
def create_tables(engine):
    """Create all tables in the database."""
    Base.metadata.create_all(engine)


def drop_tables(engine):
    """Drop all tables from the database."""
    Base.metadata.drop_all(engine)


if __name__ == "__main__":
    # Example usage and table creation
    from sqlalchemy import create_engine

    # Example connection string (replace with your actual database URL)
    DATABASE_URL = "postgresql://user:password@localhost:5432/your_database"

    engine = create_engine(DATABASE_URL)

    # Enable pgvector extension (run this once in your database)
    with engine.connect() as conn:
        conn.execute("CREATE EXTENSION IF NOT EXISTS vector;")
        conn.commit()

    # Create tables
    create_tables(engine)

    print("Tables created successfully!")
    print("Available models: Concept, ConceptSynonym, ConceptRelation, Document")
