"""newsletter_subscribers + feedback tablolari, portfolio.buy_date

Revision ID: c4d5e6f7a8b9
Revises: b3c4d5e6f7a8
Create Date: 2026-11-14

Bu migration uygulama acilisinda surec icinde calisir (backend/migrate_boot.py)
ve deploy sirasinda eski/yeni surum kisa sure birlikte ayakta olabilir; bu
yuzden her adim "zaten var mi?" kontroluyle idempotenttir ve yalnizca eklemelidir.
"""
from alembic import op
import sqlalchemy as sa


revision = 'c4d5e6f7a8b9'
down_revision = 'b3c4d5e6f7a8'
branch_labels = None
depends_on = None


def upgrade():
    insp = sa.inspect(op.get_bind())
    tables = set(insp.get_table_names())

    if 'newsletter_subscribers' not in tables:
        op.create_table(
            'newsletter_subscribers',
            sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
            sa.Column('email', sa.String(length=255), nullable=False),
            sa.Column('source', sa.String(length=32), nullable=False),
            sa.Column('subscribed_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
            sa.Column('unsubscribe_token', sa.String(length=64), nullable=False),
            sa.Column('unsubscribed_at', sa.DateTime(timezone=True), nullable=True),
            sa.Column('last_issue_key', sa.String(length=16), nullable=True),
            sa.PrimaryKeyConstraint('id'),
        )
        with op.batch_alter_table('newsletter_subscribers', schema=None) as batch_op:
            batch_op.create_index(batch_op.f('ix_newsletter_subscribers_email'), ['email'], unique=True)
            batch_op.create_index(batch_op.f('ix_newsletter_subscribers_unsubscribe_token'), ['unsubscribe_token'], unique=True)

    if 'feedback' not in tables:
        op.create_table(
            'feedback',
            sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
            sa.Column('category', sa.String(length=16), nullable=False),
            sa.Column('message', sa.Text(), nullable=False),
            sa.Column('email', sa.String(length=255), nullable=True),
            sa.PrimaryKeyConstraint('id'),
        )

    portfolio_cols = {c['name'] for c in insp.get_columns('portfolio')}
    if 'buy_date' not in portfolio_cols:
        with op.batch_alter_table('portfolio', schema=None) as batch_op:
            batch_op.add_column(sa.Column('buy_date', sa.Date(), nullable=True))


def downgrade():
    insp = sa.inspect(op.get_bind())
    tables = set(insp.get_table_names())

    if 'buy_date' in {c['name'] for c in insp.get_columns('portfolio')}:
        with op.batch_alter_table('portfolio', schema=None) as batch_op:
            batch_op.drop_column('buy_date')
    if 'feedback' in tables:
        op.drop_table('feedback')
    if 'newsletter_subscribers' in tables:
        with op.batch_alter_table('newsletter_subscribers', schema=None) as batch_op:
            batch_op.drop_index(batch_op.f('ix_newsletter_subscribers_unsubscribe_token'))
            batch_op.drop_index(batch_op.f('ix_newsletter_subscribers_email'))
        op.drop_table('newsletter_subscribers')
