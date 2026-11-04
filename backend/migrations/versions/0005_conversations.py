"""T06 迁移：个人会话、消息、来源引用与问答请求。

Revision ID: 0005_conversations
Revises: 0004_retrieval
Create Date: 2026-10-28

只新增本阶段持久结构，不改 0001～0004、不清库、不重算知识库 revision。
数据库约束承担两件关键不变量：
- ``uq_conversation_requests_client_id``：会话内 client_request_id 唯一；
- ``uq_conversation_requests_running``（部分唯一索引）：每会话最多一个 running 请求。
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0005_conversations"
down_revision = "0004_retrieval"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "conversations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_conversations_user", ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name="pk_conversations"),
    )
    op.create_index("ix_conversations_user_created", "conversations", ["user_id", "created_at"], unique=False)
    op.create_index("ix_conversations_user_deleted", "conversations", ["user_id", "deleted_at"], unique=False)

    op.create_table(
        "conversation_messages",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("conversation_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=True),
        sa.Column("revision", sa.Integer(), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("missing_fields", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["conversations.id"],
            name="fk_conversation_messages_conversation",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_conversation_messages_user", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_conversation_messages"),
        sa.UniqueConstraint("conversation_id", "seq", name="uq_conversation_messages_seq"),
    )
    op.create_index(
        "ix_conversation_messages_conversation", "conversation_messages", ["conversation_id", "seq"], unique=False
    )
    op.create_index("ix_conversation_messages_user", "conversation_messages", ["user_id"], unique=False)

    op.create_table(
        "conversation_requests",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("conversation_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("client_request_id", sa.Uuid(), nullable=False),
        sa.Column("payload_sha256", sa.String(length=64), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("user_message_id", sa.Uuid(), nullable=True),
        sa.Column("result_message_id", sa.Uuid(), nullable=True),
        sa.Column("result_json", sa.JSON(), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("error_retryable", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deadline_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["conversations.id"],
            name="fk_conversation_requests_conversation",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_conversation_requests_user", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["user_message_id"],
            ["conversation_messages.id"],
            name="fk_conversation_requests_user_message",
        ),
        sa.ForeignKeyConstraint(
            ["result_message_id"],
            ["conversation_messages.id"],
            name="fk_conversation_requests_result_message",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_conversation_requests"),
        sa.UniqueConstraint(
            "conversation_id", "client_request_id", name="uq_conversation_requests_client_id"
        ),
    )
    op.create_index(
        "ix_conversation_requests_conversation",
        "conversation_requests",
        ["conversation_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_conversation_requests_status_deadline",
        "conversation_requests",
        ["status", "deadline_at"],
        unique=False,
    )
    op.create_index(
        "uq_conversation_requests_running",
        "conversation_requests",
        ["conversation_id"],
        unique=True,
        sqlite_where=sa.text("status = 'running'"),
    )

    op.create_table(
        "conversation_message_sources",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("message_id", sa.Uuid(), nullable=False),
        sa.Column("source_id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("version_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["message_id"],
            ["conversation_messages.id"],
            name="fk_conversation_message_sources_message",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["source_id", "version_id", "document_id"],
            ["source_units.id", "source_units.version_id", "source_units.document_id"],
            name="fk_conversation_message_sources_unit",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_conversation_message_sources"),
        sa.UniqueConstraint("message_id", "source_id", name="uq_conversation_message_sources_pair"),
    )
    op.create_index(
        "ix_conversation_message_sources_message",
        "conversation_message_sources",
        ["message_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_conversation_message_sources_message", table_name="conversation_message_sources")
    op.drop_table("conversation_message_sources")
    op.drop_index("uq_conversation_requests_running", table_name="conversation_requests")
    op.drop_index("ix_conversation_requests_status_deadline", table_name="conversation_requests")
    op.drop_index("ix_conversation_requests_conversation", table_name="conversation_requests")
    op.drop_table("conversation_requests")
    op.drop_index("ix_conversation_messages_user", table_name="conversation_messages")
    op.drop_index("ix_conversation_messages_conversation", table_name="conversation_messages")
    op.drop_table("conversation_messages")
    op.drop_index("ix_conversations_user_deleted", table_name="conversations")
    op.drop_index("ix_conversations_user_created", table_name="conversations")
    op.drop_table("conversations")
