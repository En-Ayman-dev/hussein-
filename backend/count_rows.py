import os
from pathlib import Path
from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from core.models import Concept, ConceptRelation, ConceptSynonym, Document, Base

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")
DATABASE_URL = os.getenv('DATABASE_URL')

if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL is not configured")

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(bind=engine)

from sqlalchemy import text

# ensure vector extension and tables
with engine.connect() as conn:
    conn.execute(text('CREATE EXTENSION IF NOT EXISTS vector;'))
    conn.commit()
Base.metadata.create_all(engine)

session = SessionLocal()
try:
    c = session.query(Concept).count()
    r = session.query(ConceptRelation).count()
    s = session.query(ConceptSynonym).count()
    d = session.query(Document).count()
    print('concepts:', c)
    print('relations:', r)
    print('synonyms:', s)
    print('documents:', d)
finally:
    session.close()
