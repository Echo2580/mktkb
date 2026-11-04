"""T07 迁移：OCR 调用记录/成功检查点。

Revision ID: 0006_ocr_call_records
Revises: 0005_conversations
Create Date: 2026-10-29

只新增本阶段持久结构，不改 0001～0005、不清库、不重算知识库 revision。
- ``uq_ocr_call_records_success``（部分唯一索引）：同版本/页/模式/块/图片哈希最多一条成功记录，
  用于重试复用成功检查点；
- 失败/丢弃行保留尝试次数与稳定错误码，用于排错，不作为账号余额证明。
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0006_ocr_call_records"
down_revision = "0005_conversations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ocr_call_records",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("version_id", sa.Uuid(), nullable=False),
        sa.Column("page", sa.Integer(), nullable=False),
        sa.Column("mode", sa.String(length=16), nullable=False),
        sa.Column("bbox_key", sa.String(length=128), nullable=False),
        sa.Column("bbox", sa.JSON(), nullable=True),
        sa.Column("image_sha256", sa.String(length=64), nullable=False),
        sa.Column("image_bytes", sa.Integer(), nullable=False),
        sa.Column("mime_type", sa.String(length=64), nullable=False),
        sa.Column("state", sa.String(length=16), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("provider_request_id", sa.String(length=128), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("result", sa.JSON(), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["document_id"], ["documents.id"], name="fk_ocr_call_document", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["version_id"], ["document_versions.id"], name="fk_ocr_call_version", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_ocr_call_records"),
    )
    op.create_index(
        "ix_ocr_call_records_version_page",
        "ocr_call_records",
        ["version_id", "page", "mode"],
        unique=False,
    )
    op.create_index(
        "uq_ocr_call_records_success",
        "ocr_call_records",
        ["version_id", "page", "mode", "bbox_key", "image_sha256"],
        unique=True,
        sqlite_where=sa.text("state = 'succeeded'"),
    )


def downgrade() -> None:
    op.drop_index("uq_ocr_call_records_success", table_name="ocr_call_records")
    op.drop_index("ix_ocr_call_records_version_page", table_name="ocr_call_records")
    op.drop_table("ocr_call_records")
