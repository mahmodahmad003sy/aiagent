"""add chat widget tables

Revision ID: e5f6a7b8c9d0
Revises: d4c1a8e37b62
Create Date: 2026-10-01 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'e5f6a7b8c9d0'
down_revision: str | None = 'd4c1a8e37b62'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    existing_tables = set(inspector.get_table_names())

    if 'chat_widget' not in existing_tables:
        op.create_table(
            'chat_widget',
            sa.Column('id', sa.Text(), primary_key=True),
            sa.Column('user_id', sa.Text(), nullable=False),
            sa.Column('name', sa.Text(), nullable=False),
            sa.Column('model_id', sa.Text(), nullable=False),
            sa.Column('system_prompt', sa.Text(), nullable=True),
            sa.Column('welcome_message', sa.Text(), nullable=True),
            sa.Column('token', sa.Text(), nullable=False),
            sa.Column('enabled', sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column('allowed_domains', sa.JSON(), nullable=True),
            sa.Column('created_at', sa.BigInteger(), nullable=False),
            sa.Column('updated_at', sa.BigInteger(), nullable=False),
            sa.UniqueConstraint('token', name='chat_widget_token_key'),
        )
        op.create_index('ix_chat_widget_user_id', 'chat_widget', ['user_id'])
        op.create_index('ix_chat_widget_model_id', 'chat_widget', ['model_id'])
        op.create_index('ix_chat_widget_token', 'chat_widget', ['token'])
        op.create_index('ix_chat_widget_enabled', 'chat_widget', ['enabled'])
        op.create_index('ix_chat_widget_created_at', 'chat_widget', ['created_at'])
        op.create_index('ix_chat_widget_updated_at', 'chat_widget', ['updated_at'])
        op.create_index('chat_widget_user_updated_idx', 'chat_widget', ['user_id', 'updated_at'])
        op.create_index('chat_widget_user_enabled_idx', 'chat_widget', ['user_id', 'enabled'])

    if 'chat_widget_session' not in existing_tables:
        op.create_table(
            'chat_widget_session',
            sa.Column('id', sa.Text(), primary_key=True),
            sa.Column('widget_id', sa.Text(), nullable=False),
            sa.Column('visitor_id', sa.Text(), nullable=False),
            sa.Column('title', sa.Text(), nullable=True),
            sa.Column('model_id', sa.Text(), nullable=True),
            sa.Column('message_count', sa.BigInteger(), nullable=False, server_default='0'),
            sa.Column('created_at', sa.BigInteger(), nullable=False),
            sa.Column('updated_at', sa.BigInteger(), nullable=False),
            sa.Column('last_activity_at', sa.BigInteger(), nullable=False),
            sa.ForeignKeyConstraint(['widget_id'], ['chat_widget.id'], ondelete='CASCADE'),
        )
        op.create_index('ix_chat_widget_session_widget_id', 'chat_widget_session', ['widget_id'])
        op.create_index('ix_chat_widget_session_visitor_id', 'chat_widget_session', ['visitor_id'])
        op.create_index('ix_chat_widget_session_model_id', 'chat_widget_session', ['model_id'])
        op.create_index('ix_chat_widget_session_created_at', 'chat_widget_session', ['created_at'])
        op.create_index('ix_chat_widget_session_updated_at', 'chat_widget_session', ['updated_at'])
        op.create_index('ix_chat_widget_session_last_activity_at', 'chat_widget_session', ['last_activity_at'])
        op.create_index(
            'chat_widget_session_widget_updated_idx',
            'chat_widget_session',
            ['widget_id', 'updated_at'],
        )
        op.create_index(
            'chat_widget_session_widget_visitor_idx',
            'chat_widget_session',
            ['widget_id', 'visitor_id'],
        )

    if 'chat_widget_message' not in existing_tables:
        op.create_table(
            'chat_widget_message',
            sa.Column('id', sa.Text(), primary_key=True),
            sa.Column('session_id', sa.Text(), nullable=False),
            sa.Column('widget_id', sa.Text(), nullable=False),
            sa.Column('role', sa.Text(), nullable=False),
            sa.Column('content', sa.JSON(), nullable=True),
            sa.Column('model_id', sa.Text(), nullable=True),
            sa.Column('done', sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column('error', sa.JSON(), nullable=True),
            sa.Column('usage', sa.JSON(), nullable=True),
            sa.Column('created_at', sa.BigInteger(), nullable=False),
            sa.Column('updated_at', sa.BigInteger(), nullable=False),
            sa.ForeignKeyConstraint(['session_id'], ['chat_widget_session.id'], ondelete='CASCADE'),
            sa.ForeignKeyConstraint(['widget_id'], ['chat_widget.id'], ondelete='CASCADE'),
        )
        op.create_index('ix_chat_widget_message_session_id', 'chat_widget_message', ['session_id'])
        op.create_index('ix_chat_widget_message_widget_id', 'chat_widget_message', ['widget_id'])
        op.create_index('ix_chat_widget_message_model_id', 'chat_widget_message', ['model_id'])
        op.create_index('ix_chat_widget_message_created_at', 'chat_widget_message', ['created_at'])
        op.create_index(
            'chat_widget_message_session_created_idx',
            'chat_widget_message',
            ['session_id', 'created_at'],
        )
        op.create_index(
            'chat_widget_message_widget_created_idx',
            'chat_widget_message',
            ['widget_id', 'created_at'],
        )


def downgrade() -> None:
    op.drop_index('chat_widget_message_widget_created_idx', table_name='chat_widget_message')
    op.drop_index('chat_widget_message_session_created_idx', table_name='chat_widget_message')
    op.drop_index('ix_chat_widget_message_created_at', table_name='chat_widget_message')
    op.drop_index('ix_chat_widget_message_model_id', table_name='chat_widget_message')
    op.drop_index('ix_chat_widget_message_widget_id', table_name='chat_widget_message')
    op.drop_index('ix_chat_widget_message_session_id', table_name='chat_widget_message')
    op.drop_table('chat_widget_message')

    op.drop_index('chat_widget_session_widget_visitor_idx', table_name='chat_widget_session')
    op.drop_index('chat_widget_session_widget_updated_idx', table_name='chat_widget_session')
    op.drop_index('ix_chat_widget_session_last_activity_at', table_name='chat_widget_session')
    op.drop_index('ix_chat_widget_session_updated_at', table_name='chat_widget_session')
    op.drop_index('ix_chat_widget_session_created_at', table_name='chat_widget_session')
    op.drop_index('ix_chat_widget_session_model_id', table_name='chat_widget_session')
    op.drop_index('ix_chat_widget_session_visitor_id', table_name='chat_widget_session')
    op.drop_index('ix_chat_widget_session_widget_id', table_name='chat_widget_session')
    op.drop_table('chat_widget_session')

    op.drop_index('chat_widget_user_enabled_idx', table_name='chat_widget')
    op.drop_index('chat_widget_user_updated_idx', table_name='chat_widget')
    op.drop_index('ix_chat_widget_updated_at', table_name='chat_widget')
    op.drop_index('ix_chat_widget_created_at', table_name='chat_widget')
    op.drop_index('ix_chat_widget_enabled', table_name='chat_widget')
    op.drop_index('ix_chat_widget_token', table_name='chat_widget')
    op.drop_index('ix_chat_widget_model_id', table_name='chat_widget')
    op.drop_index('ix_chat_widget_user_id', table_name='chat_widget')
    op.drop_table('chat_widget')
