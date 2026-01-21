"""Increase AI settings string column limits

Revision ID: 20260121_0022
Revises: 20260120_0021
Create Date: 2026-01-21

Some AI providers use longer identifiers:
- API keys: JWT-based tokens can exceed 500 chars
- Model names: Ollama/HuggingFace models can be very long
  (e.g. huggingface.co/unsloth/Qwen3-Coder-30B-A3B-Instruct-GGUF:latest)
- Base URLs: Complex URLs with paths and query params

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20260121_0022"
down_revision: Union[str, None] = "20260120_0021"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Increase limits in app_settings
    with op.batch_alter_table("app_settings") as batch:
        batch.alter_column("ai_api_key", type_=sa.String(2000))
        batch.alter_column("ai_base_url", type_=sa.String(1000))
        batch.alter_column("ai_model", type_=sa.String(500))

    # Increase limits in guild_settings
    with op.batch_alter_table("guild_settings") as batch:
        batch.alter_column("ai_api_key", type_=sa.String(2000))
        batch.alter_column("ai_base_url", type_=sa.String(1000))
        batch.alter_column("ai_model", type_=sa.String(500))

    # Increase limits in users
    with op.batch_alter_table("users") as batch:
        batch.alter_column("ai_api_key", type_=sa.String(2000))
        batch.alter_column("ai_base_url", type_=sa.String(1000))
        batch.alter_column("ai_model", type_=sa.String(500))


def downgrade() -> None:
    # Revert to original limits in users
    with op.batch_alter_table("users") as batch:
        batch.alter_column("ai_model", type_=sa.String(100))
        batch.alter_column("ai_base_url", type_=sa.String(500))
        batch.alter_column("ai_api_key", type_=sa.String(500))

    # Revert to original limits in guild_settings
    with op.batch_alter_table("guild_settings") as batch:
        batch.alter_column("ai_model", type_=sa.String(100))
        batch.alter_column("ai_base_url", type_=sa.String(500))
        batch.alter_column("ai_api_key", type_=sa.String(500))

    # Revert to original limits in app_settings
    with op.batch_alter_table("app_settings") as batch:
        batch.alter_column("ai_model", type_=sa.String(100))
        batch.alter_column("ai_base_url", type_=sa.String(500))
        batch.alter_column("ai_api_key", type_=sa.String(500))
