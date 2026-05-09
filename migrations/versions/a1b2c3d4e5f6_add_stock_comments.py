"""add stock_comments table

Revision ID: a1b2c3d4e5f6
Revises: 2c546aa52be9
Create Date: 2026-05-09
"""
from alembic import op
import sqlalchemy as sa


revision = 'a1b2c3d4e5f6'
down_revision = '2c546aa52be9'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'stock_comments',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('user_id', sa.String(length=36), nullable=False),
        sa.Column('symbol', sa.String(length=32), nullable=False),
        sa.Column('body', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('stock_comments', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_stock_comments_symbol'), ['symbol'], unique=False)
        batch_op.create_index(batch_op.f('ix_stock_comments_user_id'), ['user_id'], unique=False)


def downgrade():
    with op.batch_alter_table('stock_comments', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_stock_comments_user_id'))
        batch_op.drop_index(batch_op.f('ix_stock_comments_symbol'))
    op.drop_table('stock_comments')
