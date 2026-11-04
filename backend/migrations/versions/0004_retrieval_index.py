"""T05 迁移：检索索引结构（版本就绪状态、单元映射、字段索引、FTS5 正文索引）。

Revision ID: 0004_retrieval
Revises: 0003_lifecycle
Create Date: 2026-10-28

只建结构，不把未完成的回填伪装成就绪：升级后既有已发布版本需要显式
`backfill_published_indexes`（见 README），未就绪时检索抛 IndexNotReady。
FTS5 虚拟表由原生 SQL 建立；其 rowid 只通过 retrieval_unit_index 映射，
不能作为客户端授权依据。
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0004_retrieval"
down_revision = "0003_lifecycle"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 复合归属的父键：SQLite 外键必须指向 PRIMARY KEY 或 UNIQUE 索引。
    # 不改 0001～0003 的表结构，只新增唯一索引供本轮新表引用。
    op.create_index(
        "uq_source_units_identity",
        "source_units",
        ["id", "version_id", "document_id"],
        unique=True,
    )
    op.create_index(
        "uq_document_versions_identity",
        "document_versions",
        ["id", "document_id"],
        unique=True,
    )

    op.create_table(
        "retrieval_version_index",
        sa.Column("version_id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("unit_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("input_digest", sa.String(length=64), nullable=False),
        sa.Column("tokenizer_version", sa.String(length=80), nullable=False),
        sa.Column("ready", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("prepared_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["version_id"], ["document_versions.id"], name="fk_retrieval_version_index_version", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["document_id"], ["documents.id"], name="fk_retrieval_version_index_document", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["version_id", "document_id"],
            ["document_versions.id", "document_versions.document_id"],
            name="fk_retrieval_version_index_identity",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("version_id", name="pk_retrieval_version_index"),
    )
    op.create_index(
        "ix_retrieval_version_index_document", "retrieval_version_index", ["document_id"], unique=False
    )

    op.create_table(
        "retrieval_unit_index",
        sa.Column("fts_rowid", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("unit_id", sa.Uuid(), nullable=False),
        sa.Column("version_id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("entity_type", sa.String(length=16), nullable=True),
        sa.Column("entity_key", sa.String(length=300), nullable=True),
        sa.Column("label", sa.String(length=300), nullable=True),
        sa.Column("entity_filters", sa.JSON(), nullable=True),
        sa.Column("token_count", sa.Integer(), nullable=False, server_default="0"),
        sa.ForeignKeyConstraint(
            ["unit_id"], ["source_units.id"], name="fk_retrieval_unit_index_unit", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["version_id"], ["document_versions.id"], name="fk_retrieval_unit_index_version", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["document_id"], ["documents.id"], name="fk_retrieval_unit_index_document", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["unit_id", "version_id", "document_id"],
            ["source_units.id", "source_units.version_id", "source_units.document_id"],
            name="fk_retrieval_unit_index_identity",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("fts_rowid", name="pk_retrieval_unit_index"),
        sa.UniqueConstraint("unit_id", name="uq_retrieval_unit_index_unit"),
    )
    op.create_index("ix_retrieval_unit_index_version", "retrieval_unit_index", ["version_id"], unique=False)
    op.create_index("ix_retrieval_unit_index_document", "retrieval_unit_index", ["document_id"], unique=False)
    op.create_index("ix_retrieval_unit_index_entity", "retrieval_unit_index", ["entity_key"], unique=False)

    op.create_table(
        "retrieval_field_index",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("unit_id", sa.Uuid(), nullable=False),
        sa.Column("version_id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("field_name", sa.String(length=128), nullable=False),
        sa.Column("field_role", sa.String(length=16), nullable=True),
        sa.Column("norm_value", sa.String(length=512), nullable=False),
        sa.Column("value_text", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(
            ["unit_id"], ["source_units.id"], name="fk_retrieval_field_index_unit", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["version_id"], ["document_versions.id"], name="fk_retrieval_field_index_version", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["document_id"], ["documents.id"], name="fk_retrieval_field_index_document", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["unit_id", "version_id", "document_id"],
            ["source_units.id", "source_units.version_id", "source_units.document_id"],
            name="fk_retrieval_field_index_identity",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_retrieval_field_index"),
    )
    op.create_index("ix_retrieval_field_index_unit", "retrieval_field_index", ["unit_id"], unique=False)
    op.create_index("ix_retrieval_field_index_version", "retrieval_field_index", ["version_id"], unique=False)
    op.create_index(
        "ix_retrieval_field_index_role_value",
        "retrieval_field_index",
        ["field_role", "norm_value"],
        unique=False,
    )

    op.execute(
        "CREATE VIRTUAL TABLE source_unit_fts USING fts5("
        "body, version_id UNINDEXED, tokenize='unicode61 remove_diacritics 2')"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS source_unit_fts")
    op.drop_index("ix_retrieval_field_index_role_value", table_name="retrieval_field_index")
    op.drop_index("ix_retrieval_field_index_version", table_name="retrieval_field_index")
    op.drop_index("ix_retrieval_field_index_unit", table_name="retrieval_field_index")
    op.drop_table("retrieval_field_index")
    op.drop_index("ix_retrieval_unit_index_entity", table_name="retrieval_unit_index")
    op.drop_index("ix_retrieval_unit_index_document", table_name="retrieval_unit_index")
    op.drop_index("ix_retrieval_unit_index_version", table_name="retrieval_unit_index")
    op.drop_table("retrieval_unit_index")
    op.drop_index("ix_retrieval_version_index_document", table_name="retrieval_version_index")
    op.drop_table("retrieval_version_index")
    op.drop_index("uq_document_versions_identity", table_name="document_versions")
    op.drop_index("uq_source_units_identity", table_name="source_units")
