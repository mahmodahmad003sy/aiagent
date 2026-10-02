"""chat widget v2

Revision ID: 7c2e9a41b5d3
Revises: e5f6a7b8c9d0
Create Date: 2026-10-02 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = '7c2e9a41b5d3'
down_revision: str | None = 'e5f6a7b8c9d0'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _table_names(inspector: sa.Inspector) -> set[str]:
    return set(inspector.get_table_names())


def _column_names(inspector: sa.Inspector, table: str) -> set[str]:
    return {column['name'] for column in inspector.get_columns(table)}


def _index_names(inspector: sa.Inspector, table: str) -> set[str]:
    return {index['name'] for index in inspector.get_indexes(table)}


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    tables = _table_names(inspector)

    if 'chat_widget' in tables:
        columns = _column_names(inspector, 'chat_widget')
        with op.batch_alter_table('chat_widget') as batch_op:
            if 'theme' not in columns:
                batch_op.add_column(sa.Column('theme', sa.JSON(), nullable=True))
            if 'mcp_enabled' not in columns:
                batch_op.add_column(
                    sa.Column(
                        'mcp_enabled',
                        sa.Boolean(),
                        nullable=False,
                        server_default=sa.false(),
                    )
                )
            if 'mcp_tool_ids' not in columns:
                batch_op.add_column(sa.Column('mcp_tool_ids', sa.JSON(), nullable=True))
            if 'folder_id' not in columns:
                batch_op.add_column(sa.Column('folder_id', sa.Text(), nullable=True))

    if 'chat_widget_session' in tables:
        columns = _column_names(inspector, 'chat_widget_session')
        indexes = _index_names(inspector, 'chat_widget_session')
        with op.batch_alter_table('chat_widget_session') as batch_op:
            if 'chat_id' not in columns:
                batch_op.add_column(sa.Column('chat_id', sa.Text(), nullable=True))
            if 'chat_last_message_id' not in columns:
                batch_op.add_column(sa.Column('chat_last_message_id', sa.Text(), nullable=True))
            if 'ix_chat_widget_session_chat_id' not in indexes:
                batch_op.create_index('ix_chat_widget_session_chat_id', ['chat_id'])


def downgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    tables = _table_names(inspector)

    if 'chat_widget_session' in tables:
        indexes = _index_names(inspector, 'chat_widget_session')
        columns = _column_names(inspector, 'chat_widget_session')
        with op.batch_alter_table('chat_widget_session') as batch_op:
            if 'ix_chat_widget_session_chat_id' in indexes:
                batch_op.drop_index('ix_chat_widget_session_chat_id')
            if 'chat_last_message_id' in columns:
                batch_op.drop_column('chat_last_message_id')
            if 'chat_id' in columns:
                batch_op.drop_column('chat_id')

    if 'chat_widget' in tables:
        columns = _column_names(inspector, 'chat_widget')
        with op.batch_alter_table('chat_widget') as batch_op:
            if 'folder_id' in columns:
                batch_op.drop_column('folder_id')
            if 'mcp_tool_ids' in columns:
                batch_op.drop_column('mcp_tool_ids')
            if 'mcp_enabled' in columns:
                batch_op.drop_column('mcp_enabled')
            if 'theme' in columns:
                batch_op.drop_column('theme')
