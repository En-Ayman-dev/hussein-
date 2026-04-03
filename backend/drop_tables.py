import os
from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from core.models import Base

load_dotenv()
DATABASE_URL = os.getenv("DATABASE_URL")

engine = create_engine(DATABASE_URL)

# Drop all tables
Base.metadata.drop_all(engine)
print("Tables dropped successfully.")