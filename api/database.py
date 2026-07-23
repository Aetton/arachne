"""Database models.

PostgreSQL is the production default. SQLite remains supported for development
and for the one-shot migration utility.
"""
import os
from datetime import datetime, timezone

from sqlalchemy import (
    create_engine, Column, Integer, String, Boolean, JSON, DateTime, ForeignKey,
    Text, UniqueConstraint,
)
from sqlalchemy.orm import declarative_base, sessionmaker, relationship

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+psycopg://arachne:arachne@db:5432/arachne",
)

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


class Role(Base):
    __tablename__ = "roles"

    id = Column(Integer, primary_key=True)
    slug = Column(String(64), unique=True, index=True, nullable=False)
    name = Column(String(128), nullable=False)
    description = Column(Text, default="")
    inherits = Column(JSON, default=list)
    is_system = Column(Boolean, default=False)
    created_at = Column(DateTime, default=utcnow)


class Permission(Base):
    __tablename__ = "permissions"

    id = Column(Integer, primary_key=True)
    slug = Column(String(96), unique=True, index=True, nullable=False)
    description = Column(Text, default="")


class RolePermission(Base):
    __tablename__ = "role_permissions"
    __table_args__ = (UniqueConstraint("role_id", "permission_id"),)

    id = Column(Integer, primary_key=True)
    role_id = Column(Integer, ForeignKey("roles.id", ondelete="CASCADE"), nullable=False)
    permission_id = Column(Integer, ForeignKey("permissions.id", ondelete="CASCADE"), nullable=False)

    role = relationship("Role")
    permission = relationship("Permission")


class Component(Base):
    __tablename__ = "components"

    slug = Column(String(96), primary_key=True)
    label = Column(String(160), nullable=False)
    icon = Column(String(64), default="ti-box", nullable=False)
    sort_order = Column(Integer, default=0, nullable=False)
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

    scenarios = relationship("Scenario", back_populates="component_ref")


class Scenario(Base):
    __tablename__ = "scenarios"

    id = Column(Integer, primary_key=True)
    slug = Column(String(96), unique=True, index=True, nullable=False)
    label = Column(String(160), nullable=False)
    component = Column(
        String(96),
        ForeignKey("components.slug", ondelete="RESTRICT", onupdate="CASCADE"),
        index=True,
        nullable=False,
    )
    enabled = Column(Boolean, default=True)
    current_version_id = Column(Integer, nullable=True)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

    versions = relationship(
        "ScenarioVersion",
        back_populates="scenario",
        foreign_keys="ScenarioVersion.scenario_id",
        cascade="all, delete-orphan",
    )
    component_ref = relationship("Component", back_populates="scenarios")


class ScenarioVersion(Base):
    __tablename__ = "scenario_versions"
    __table_args__ = (UniqueConstraint("scenario_id", "version"),)

    id = Column(Integer, primary_key=True)
    scenario_id = Column(Integer, ForeignKey("scenarios.id", ondelete="CASCADE"), nullable=False)
    version = Column(Integer, nullable=False)
    definition = Column(JSON, nullable=False)
    status = Column(String(16), default="draft")  # draft|published|archived
    comment = Column(Text, default="")
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=utcnow)

    scenario = relationship("Scenario", back_populates="versions", foreign_keys=[scenario_id])


class ScenarioACL(Base):
    __tablename__ = "scenario_acl"
    __table_args__ = (
        UniqueConstraint(
            "scenario_id", "subject_type", "subject_key", "permission", "effect",
        ),
    )

    id = Column(Integer, primary_key=True)
    scenario_id = Column(Integer, ForeignKey("scenarios.id", ondelete="CASCADE"), nullable=False)
    subject_type = Column(String(16), nullable=False)  # role|team
    subject_key = Column(String(96), nullable=False)  # role slug or team id
    permission = Column(String(16), nullable=False)   # view|run|edit|manage
    effect = Column(String(8), default="allow")       # allow|deny
    match_mode = Column(String(8), default="all")     # all|any


class Run(Base):
    __tablename__ = "runs"

    id = Column(String(36), primary_key=True)   # uuid4 str
    user_id = Column(Integer, ForeignKey("users.id"))
    scenario = Column(String(64), nullable=False)
    scenario_version_id = Column(
        Integer, ForeignKey("scenario_versions.id"), nullable=True,
    )
    scenario_snapshot = Column(JSON, nullable=True)
    params = Column(JSON, default=dict)
    status = Column(String(16), default="running")   # running|success|failed|cancelled
    created_at = Column(DateTime, default=utcnow)
    completed_at = Column(DateTime, nullable=True)
    log = Column(Text, default="")           # raw stdout, appended live
    artifacts = Column(JSON, default=list)   # [{name, repo, path}]

    user = relationship("User")


def init_db():
    if DATABASE_URL.startswith("sqlite"):
        os.makedirs("./data", exist_ok=True)
    Base.metadata.create_all(bind=engine)
