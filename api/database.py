"""
Database layer. SQLite by default, swap DATABASE_URL for Postgres later.

    sqlite:  sqlite:///./data/arachne.db
    postgres: postgresql+psycopg://user:pass@host/arachne

JSON columns work on both backends (SQLAlchemy emits JSON on PG, TEXT-JSON on SQLite).
"""
import os
from datetime import datetime, timezone

from sqlalchemy import (
    create_engine, Column, Integer, String, Boolean, JSON, DateTime, ForeignKey, Text,
)
from sqlalchemy.orm import declarative_base, sessionmaker, relationship

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./data/arachne.db")

# check_same_thread only matters for SQLite; ignored elsewhere.
connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, connect_args=connect_args, future=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine, future=True)
Base = declarative_base()


def utcnow():
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    username = Column(String(64), unique=True, index=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    full_name = Column(String(128), default="")
    # auth_source: "local" now, "ldap" later — lets both coexist
    auth_source = Column(String(16), default="local")
    roles = Column(JSON, default=list)   # ["admin", "developer", "tester"]
    teams = Column(JSON, default=list)   # [team_id, ...]
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=utcnow)
    last_login = Column(DateTime, nullable=True)


class Team(Base):
    __tablename__ = "teams"

    id = Column(Integer, primary_key=True)
    slug = Column(String(64), unique=True, index=True, nullable=False)
    name = Column(String(128), nullable=False)
    components = Column(JSON, default=list)   # ["frontend", "broker"] or ["*"]
    artifact_repo = Column(String(64), default="dev-artifacts")


class Run(Base):
    __tablename__ = "runs"

    id = Column(String(36), primary_key=True)   # uuid4 str
    user_id = Column(Integer, ForeignKey("users.id"))
    scenario = Column(String(64), nullable=False)
    params = Column(JSON, default=dict)
    status = Column(String(16), default="running")   # running|success|failed|cancelled
    created_at = Column(DateTime, default=utcnow)
    completed_at = Column(DateTime, nullable=True)
    log = Column(Text, default="")           # raw stdout, appended live
    artifacts = Column(JSON, default=list)   # [{name, repo, path}]

    user = relationship("User")


def init_db():
    os.makedirs("./data", exist_ok=True)
    Base.metadata.create_all(bind=engine)
