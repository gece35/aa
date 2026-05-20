"""add tweet_logs table

Revision ID: b3c4d5e6f7a8
Revises: a1b2c3d4e5f6
Create Date: 2026-05-19
"""
from alembic import op
import sqlalchemy as sa


revision = 'b3c4d5e6f7a8'
down_revision = 'a1b2c3d4e5f6'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'tweet_logs',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('symbol', sa.String(length=32), nullable=False),
        sa.Column('score', sa.Integer(), nullable=False),
        sa.Column('tweet_id', sa.String(length=64), nullable=True),
        sa.Column('tweeted_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('tweet_logs', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_tweet_logs_symbol'), ['symbol'], unique=False)
        batch_op.create_index('ix_tweet_logs_symbol_date', ['symbol', 'tweeted_at'], unique=False)


def downgrade():
    with op.batch_alter_table('tweet_logs', schema=None) as batch_op:
        batch_op.drop_index('ix_tweet_logs_symbol_date')
        batch_op.drop_index(batch_op.f('ix_tweet_logs_symbol'))
    op.drop_table('tweet_logs')
