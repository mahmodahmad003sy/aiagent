"""chat widget website crawl

Revision ID: a1c4e7b9d2f3
Revises: 7c2e9a41b5d3
Create Date: 2026-10-03 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'a1c4e7b9d2f3'
down_revision: str | None = '7c2e9a41b5d3'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    tables = set(inspector.get_table_names())

    if 'chat_widget' in tables:
        columns = {column['name'] for column in inspector.get_columns('chat_widget')}
        if 'knowledge_id' not in columns:
            with op.batch_alter_table('chat_widget') as batch_op:
                batch_op.add_column(sa.Column('knowledge_id', sa.Text(), nullable=True))

    if 'chat_widget_crawl_config' not in tables:
        op.create_table(
            'chat_widget_crawl_config',
            sa.Column('id', sa.Text(), primary_key=True),
            sa.Column('widget_id', sa.Text(), sa.ForeignKey('chat_widget.id', ondelete='CASCADE'), nullable=False),
            sa.Column('settings', sa.JSON(), nullable=False),
            sa.Column('created_at', sa.BigInteger(), nullable=False),
            sa.Column('updated_at', sa.BigInteger(), nullable=False),
        )
        op.create_index(
            'ix_chat_widget_crawl_config_widget_id', 'chat_widget_crawl_config', ['widget_id'], unique=True
        )

    if 'chat_widget_crawl_run' not in tables:
        op.create_table(
            'chat_widget_crawl_run',
            sa.Column('id', sa.Text(), primary_key=True),
            sa.Column('widget_id', sa.Text(), sa.ForeignKey('chat_widget.id', ondelete='CASCADE'), nullable=False),
            sa.Column('user_id', sa.Text(), nullable=False),
            sa.Column('settings', sa.JSON(), nullable=False),
            sa.Column('status', sa.Text(), nullable=False),
            sa.Column('progress', sa.JSON(), nullable=True),
            sa.Column('error', sa.Text(), nullable=True),
            sa.Column('cancel_requested', sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column('heartbeat_at', sa.BigInteger(), nullable=True),
            sa.Column('started_at', sa.BigInteger(), nullable=True),
            sa.Column('finished_at', sa.BigInteger(), nullable=True),
            sa.Column('extend_status', sa.Text(), nullable=True),
            sa.Column('extend_progress', sa.JSON(), nullable=True),
            sa.Column('extend_error', sa.Text(), nullable=True),
            sa.Column('extend_started_at', sa.BigInteger(), nullable=True),
            sa.Column('extend_finished_at', sa.BigInteger(), nullable=True),
            sa.Column('created_at', sa.BigInteger(), nullable=False),
        )
        op.create_index(
            'ix_chat_widget_crawl_run_widget_created', 'chat_widget_crawl_run', ['widget_id', 'created_at']
        )

    if 'chat_widget_crawl_item' not in tables:
        op.create_table(
            'chat_widget_crawl_item',
            sa.Column('id', sa.Text(), primary_key=True),
            sa.Column(
                'run_id', sa.Text(), sa.ForeignKey('chat_widget_crawl_run.id', ondelete='CASCADE'), nullable=False
            ),
            sa.Column('widget_id', sa.Text(), nullable=False),
            sa.Column('kind', sa.Text(), nullable=False),
            sa.Column('url', sa.Text(), nullable=False),
            sa.Column('title', sa.Text(), nullable=True),
            sa.Column('name', sa.Text(), nullable=True),
            sa.Column('file_type', sa.Text(), nullable=True),
            sa.Column('size', sa.BigInteger(), nullable=True),
            sa.Column('depth', sa.Integer(), nullable=True),
            sa.Column('found_on', sa.Text(), nullable=True),
            sa.Column('found_on_title', sa.Text(), nullable=True),
            sa.Column('link_text', sa.Text(), nullable=True),
            sa.Column('context', sa.Text(), nullable=True),
            sa.Column('status', sa.Text(), nullable=False),
            sa.Column('http_status', sa.Integer(), nullable=True),
            sa.Column('selected', sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column('content_text', sa.Text(), nullable=True),
            sa.Column('extract_status', sa.Text(), nullable=True),
            sa.Column('extract_error', sa.Text(), nullable=True),
            sa.Column('created_at', sa.BigInteger(), nullable=False),
        )
        op.create_index('ix_chat_widget_crawl_item_run_kind', 'chat_widget_crawl_item', ['run_id', 'kind'])
        op.create_index('ix_chat_widget_crawl_item_widget_id', 'chat_widget_crawl_item', ['widget_id'])

    if 'chat_widget_knowledge_item' not in tables:
        op.create_table(
            'chat_widget_knowledge_item',
            sa.Column('id', sa.Text(), primary_key=True),
            sa.Column('widget_id', sa.Text(), sa.ForeignKey('chat_widget.id', ondelete='CASCADE'), nullable=False),
            sa.Column('kind', sa.Text(), nullable=False),
            sa.Column('url', sa.Text(), nullable=False),
            sa.Column('file_id', sa.Text(), nullable=False),
            sa.Column('content_hash', sa.Text(), nullable=False),
            sa.Column('created_at', sa.BigInteger(), nullable=False),
            sa.Column('updated_at', sa.BigInteger(), nullable=False),
            sa.UniqueConstraint('widget_id', 'kind', 'url', name='uq_chat_widget_knowledge_item_widget_kind_url'),
        )
        op.create_index('ix_chat_widget_knowledge_item_widget_id', 'chat_widget_knowledge_item', ['widget_id'])


def downgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    tables = set(inspector.get_table_names())

    if 'chat_widget_knowledge_item' in tables:
        op.drop_index('ix_chat_widget_knowledge_item_widget_id', table_name='chat_widget_knowledge_item')
        op.drop_table('chat_widget_knowledge_item')

    if 'chat_widget_crawl_item' in tables:
        op.drop_index('ix_chat_widget_crawl_item_widget_id', table_name='chat_widget_crawl_item')
        op.drop_index('ix_chat_widget_crawl_item_run_kind', table_name='chat_widget_crawl_item')
        op.drop_table('chat_widget_crawl_item')

    if 'chat_widget_crawl_run' in tables:
        op.drop_index('ix_chat_widget_crawl_run_widget_created', table_name='chat_widget_crawl_run')
        op.drop_table('chat_widget_crawl_run')

    if 'chat_widget_crawl_config' in tables:
        op.drop_index('ix_chat_widget_crawl_config_widget_id', table_name='chat_widget_crawl_config')
        op.drop_table('chat_widget_crawl_config')

    if 'chat_widget' in tables:
        columns = {column['name'] for column in inspector.get_columns('chat_widget')}
        if 'knowledge_id' in columns:
            with op.batch_alter_table('chat_widget') as batch_op:
                batch_op.drop_column('knowledge_id')
