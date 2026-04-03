import os
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import Text, create_engine, func, select, text

from core.models import Concept

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

database_url = os.getenv("DATABASE_URL")
if not database_url:
    raise RuntimeError("DATABASE_URL is not configured")

engine = create_engine(database_url)
text_fields = (
    func.coalesce(Concept.labels.cast(Text), "")
    + " "
    + func.coalesce(Concept.definition.cast(Text), "")
    + " "
    + func.coalesce(Concept.quote.cast(Text), "")
)
fts_query = func.plainto_tsquery("arabic", "ما هو معنى هدى القرآن")
statement = (
    select(
        Concept,
        func.ts_rank_cd(func.to_tsvector("arabic", text_fields), fts_query).label("rank"),
    )
    .where(func.to_tsvector("arabic", text_fields).op("@@")(fts_query))
    .order_by(text("rank DESC"))
    .limit(10)
)

print(statement)
try:
    print(str(statement.compile(dialect=engine.dialect, compile_kwargs={"literal_binds": True})))
except Exception as exc:
    print(f"Literal SQL compilation is not available for this statement: {exc}")
