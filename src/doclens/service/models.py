"""Service-owned schema. This does not reinterpret baseline document schema 1."""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, MetaData, String, UniqueConstraint, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


SCHEMA = "doclens_service"


class Base(DeclarativeBase):
    metadata = MetaData(schema=SCHEMA)


class Principal(Base):
    __tablename__ = "principals"
    __table_args__ = (UniqueConstraint("issuer", "subject", name="uq_principal_identity"),)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    issuer: Mapped[str] = mapped_column(String(2048))
    subject: Mapped[str] = mapped_column(String(255))


class Workspace(Base):
    __tablename__ = "workspaces"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    slug: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(String(120))


class Membership(Base):
    __tablename__ = "memberships"
    __table_args__ = (CheckConstraint("role IN ('owner', 'editor', 'viewer')", name="ck_membership_role"),)

    workspace_id: Mapped[UUID] = mapped_column(ForeignKey(f"{SCHEMA}.workspaces.id"), primary_key=True)
    principal_id: Mapped[UUID] = mapped_column(ForeignKey(f"{SCHEMA}.principals.id"), primary_key=True)
    role: Mapped[str] = mapped_column(String(16))


class RegisteredSource(Base):
    __tablename__ = "sources"
    __table_args__ = (
        UniqueConstraint("workspace_id", "url", "product", "version", name="uq_source_identity"),
        CheckConstraint("connector_kind = 'https_html'", name="ck_source_connector"),
        CheckConstraint("document_type IN ('reference', 'release_notes')", name="ck_source_purpose"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(ForeignKey(f"{SCHEMA}.workspaces.id"), index=True)
    created_by: Mapped[UUID] = mapped_column(ForeignKey(f"{SCHEMA}.principals.id"))
    name: Mapped[str] = mapped_column(String(120))
    connector_kind: Mapped[str] = mapped_column(String(32))
    product: Mapped[str] = mapped_column(String(64))
    version: Mapped[str] = mapped_column(String(64))
    document_type: Mapped[str] = mapped_column(String(32))
    url: Mapped[str] = mapped_column(String(2048))
    source_terms_url: Mapped[str] = mapped_column(String(2048))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
