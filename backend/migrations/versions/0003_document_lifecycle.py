"""T04 迁移：知识库 revision/有效总量、发布与删除幂等凭据。

Revision ID: 0003_lifecycle
Revises: 0002_documents
Create Date: 2026-10-28

仅新增本阶段最小持久结构；不修改 0001/0002，不清库。
knowledge_state 为单例行（id=1）：空库初始化 revision=0；
若被升级的旧库已存在人工发布的资料，则按实际有效版本重算初始总量。
"""

from __future__ import annotations

from datetime import datetime, timezone

import sqlalchemy as sa
from alembic import op

revision = "0003_lifecycle"
down_revision = "0002_documents"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "knowledge_state",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("active_document_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("active_excel_row_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_knowledge_state"),
    )

    op.create_table(
        "publication_receipts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("version_id", sa.Uuid(), nullable=False),
        sa.Column("expected_active_version_id", sa.Uuid(), nullable=True),
        sa.Column("expected_revision", sa.Integer(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["document_id"], ["documents.id"], name="fk_publication_receipts_document", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["version_id"], ["document_versions.id"], name="fk_publication_receipts_version", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_publication_receipts"),
        sa.UniqueConstraint("version_id", name="uq_publication_receipts_version"),
    )
    op.create_index("ix_publication_receipts_document", "publication_receipts", ["document_id"], unique=False)

    op.create_table(
        "deletion_receipts",
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("expected_revision", sa.Integer(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["document_id"], ["documents.id"], name="fk_deletion_receipts_document", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("document_id", name="pk_deletion_receipts"),
    )

    connection = op.get_bind()
    active_documents = int(
        connection.execute(
            sa.text(
                "SELECT COUNT(*) FROM documents d JOIN document_versions v ON v.id = d.active_version_id "
                "WHERE d.deleted = 0 AND v.state = 'published'"
            )
        ).scalar()
        or 0
    )
    active_excel_rows = int(
        connection.execute(
            sa.text(
                "SELECT COUNT(*) FROM source_units su "
                "JOIN document_versions v ON v.id = su.version_id "
                "JOIN documents d ON d.id = su.document_id "
                "WHERE d.deleted = 0 AND d.active_version_id = v.id AND v.state = 'published' "
                "AND d.file_type = 'xlsx' AND su.kind = 'table_row'"
            )
        ).scalar()
        or 0
    )
    knowledge_state = sa.table(
        "knowledge_state",
        sa.column("id", sa.Integer()),
        sa.column("revision", sa.Integer()),
        sa.column("active_document_count", sa.Integer()),
        sa.column("active_excel_row_count", sa.Integer()),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    op.bulk_insert(
        knowledge_state,
        [
            {
                "id": 1,
                "revision": 0,
                "active_document_count": active_documents,
                "active_excel_row_count": active_excel_rows,
                "updated_at": datetime.now(timezone.utc),
            }
        ],
    )


def downgrade() -> None:
    op.drop_table("deletion_receipts")
    op.drop_index("ix_publication_receipts_document", table_name="publication_receipts")
    op.drop_table("publication_receipts")
    op.drop_table("knowledge_state")
