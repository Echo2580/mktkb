"""T03 迁移：逻辑文件/版本、来源单元与导入任务。

Revision ID: 0002_documents
Revises: 0001_auth
Create Date: 2026-10-28

仅新增本阶段表/索引/约束；不修改 0001_auth，不清库。
同字节去重由 document_versions 上的部分唯一索引保证（存活状态参与唯一）；
未显式允许同名的首次创建由 documents.name_key 唯一索引保证。
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0002_documents"
down_revision = "0001_auth"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "documents",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("name_key", sa.String(length=255), nullable=True),
        sa.Column("file_type", sa.String(length=16), nullable=False),
        sa.Column("active_version_id", sa.Uuid(), nullable=True),
        sa.Column("latest_version_number", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("deleted", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_published_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["active_version_id"], ["document_versions.id"], name="fk_documents_active_version"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_documents"),
    )
    op.create_index("uq_documents_name_key", "documents", ["name_key"], unique=True)
    op.create_index("ix_documents_name", "documents", ["name"], unique=False)

    op.create_table(
        "document_versions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(length=16), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("stored_path", sa.String(length=512), nullable=False),
        sa.Column("uploaded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("processing_report", sa.JSON(), nullable=True),
        sa.ForeignKeyConstraint(
            ["document_id"], ["documents.id"], name="fk_document_versions_document", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_document_versions"),
        sa.UniqueConstraint("document_id", "number", name="uq_document_versions_number"),
    )
    op.create_index("ix_document_versions_document_id", "document_versions", ["document_id"], unique=False)
    op.create_index("ix_document_versions_sha256", "document_versions", ["sha256"], unique=False)
    op.create_index(
        "uq_document_versions_live_sha",
        "document_versions",
        ["sha256"],
        unique=True,
        sqlite_where=sa.text("state IN ('queued','processing','review_required','published')"),
    )

    op.create_table(
        "source_units",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("version_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("unit_key", sa.String(length=200), nullable=False),
        sa.Column("sheet", sa.String(length=128), nullable=True),
        sa.Column("locator", sa.JSON(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("fields", sa.JSON(), nullable=False),
        sa.Column("warnings", sa.JSON(), nullable=True),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], name="fk_source_units_document", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["version_id"], ["document_versions.id"], name="fk_source_units_version", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_source_units"),
        sa.UniqueConstraint("version_id", "unit_key", name="uq_source_units_key"),
        sa.UniqueConstraint("version_id", "ordinal", name="uq_source_units_ordinal"),
    )
    op.create_index("ix_source_units_version_id", "source_units", ["version_id"], unique=False)
    op.create_index("ix_source_units_sheet", "source_units", ["sheet"], unique=False)

    op.create_table(
        "import_jobs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("version_id", sa.Uuid(), nullable=False),
        sa.Column("state", sa.String(length=16), nullable=False),
        sa.Column("stage", sa.String(length=32), nullable=False),
        sa.Column("total_pages", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("completed_pages", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("message", sa.String(length=500), nullable=True),
        sa.Column("retryable", sa.Boolean(), nullable=False, server_default="1"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("lease_token", sa.String(length=64), nullable=True),
        sa.Column("lease_owner", sa.String(length=128), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["version_id"], ["document_versions.id"], name="fk_import_jobs_version", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_import_jobs"),
    )
    op.create_index("ux_import_jobs_version", "import_jobs", ["version_id"], unique=True)
    op.create_index("ix_import_jobs_state", "import_jobs", ["state"], unique=False)
    op.create_index("ix_import_jobs_lease_expires_at", "import_jobs", ["lease_expires_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_import_jobs_lease_expires_at", table_name="import_jobs")
    op.drop_index("ix_import_jobs_state", table_name="import_jobs")
    op.drop_index("ux_import_jobs_version", table_name="import_jobs")
    op.drop_table("import_jobs")

    op.drop_index("ix_source_units_sheet", table_name="source_units")
    op.drop_index("ix_source_units_version_id", table_name="source_units")
    op.drop_table("source_units")

    op.drop_index("uq_document_versions_live_sha", table_name="document_versions")
    op.drop_index("ix_document_versions_sha256", table_name="document_versions")
    op.drop_index("ix_document_versions_document_id", table_name="document_versions")
    op.drop_table("document_versions")

    op.drop_index("ix_documents_name", table_name="documents")
    op.drop_index("uq_documents_name_key", table_name="documents")
    op.drop_table("documents")
