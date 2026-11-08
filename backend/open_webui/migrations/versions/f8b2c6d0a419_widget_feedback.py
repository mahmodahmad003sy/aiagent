"""Add optional per-answer widget feedback and an explicit question link."""

from alembic import op
import sqlalchemy as sa

revision = 'f8b2c6d0a419'
down_revision = 'e6a4f9c2b7d1'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('chat_widget_message') as batch:
        batch.add_column(sa.Column('parent_message_id', sa.Text(), nullable=True))
        batch.add_column(sa.Column('feedback_vote', sa.BigInteger(), nullable=True))
        batch.add_column(sa.Column('feedback', sa.JSON(), nullable=True))
        batch.create_index('ix_chat_widget_message_feedback_vote', ['feedback_vote'])


def downgrade():
    with op.batch_alter_table('chat_widget_message') as batch:
        batch.drop_index('ix_chat_widget_message_feedback_vote')
        batch.drop_column('feedback')
        batch.drop_column('feedback_vote')
        batch.drop_column('parent_message_id')
