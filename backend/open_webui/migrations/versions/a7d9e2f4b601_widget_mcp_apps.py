"""Separate Workspace MCP Apps selections from native MCP servers."""
from alembic import op
import sqlalchemy as sa

revision = 'a7d9e2f4b601'
down_revision = 'f8b2c6d0a419'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('chat_widget') as batch:
        batch.add_column(sa.Column('mcp_apps_enabled', sa.Boolean(), nullable=False, server_default=sa.false()))
        batch.add_column(sa.Column('mcp_app_tool_ids', sa.JSON(), nullable=True))


def downgrade():
    with op.batch_alter_table('chat_widget') as batch:
        batch.drop_column('mcp_app_tool_ids')
        batch.drop_column('mcp_apps_enabled')
