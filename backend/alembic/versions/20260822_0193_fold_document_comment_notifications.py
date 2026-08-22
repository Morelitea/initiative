"""fold document comment notifications into comment_on_resource

A document is a tool, so a comment on one is reported by the same
``comment_on_resource`` notification every other tool uses. Existing inbox
rows move to the generic shape — ``entity_type``/``entity_id``/``entity_name``
in ``data`` — so they keep rendering. ``comment_on_task`` stays its own type:
it addresses the task's assignees, not the entity's creator.
"""

from alembic import op

revision = "20260822_0193"
down_revision = "20260821_0192"
branch_labels = None
depends_on = None

_FOLD = """
UPDATE notifications
   SET type = 'comment_on_resource',
       data = (
           (data::jsonb - 'document_id' - 'document_name' - 'document_title')
           || jsonb_build_object(
                'entity_type', 'document',
                'entity_id', data::jsonb -> 'document_id',
                'entity_name', COALESCE(
                    data::jsonb -> 'document_name',
                    data::jsonb -> 'document_title'
                )
              )
       )::json
 WHERE type = 'comment_on_document'
"""

_UNFOLD = """
UPDATE notifications
   SET type = 'comment_on_document',
       data = (
           (data::jsonb - 'entity_type' - 'entity_id' - 'entity_name')
           || jsonb_build_object(
                'document_id', data::jsonb -> 'entity_id',
                'document_name', data::jsonb -> 'entity_name'
              )
       )::json
 WHERE type = 'comment_on_resource'
   AND data::jsonb ->> 'entity_type' = 'document'
"""


def upgrade() -> None:
    # The table is FORCE RLS; the owning role lifts it for the rewrite and
    # restores it, as 0190 did for resource_grants.
    op.execute("ALTER TABLE notifications NO FORCE ROW LEVEL SECURITY")
    try:
        op.execute(_FOLD)
    finally:
        op.execute("ALTER TABLE notifications FORCE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.execute("ALTER TABLE notifications NO FORCE ROW LEVEL SECURITY")
    try:
        op.execute(_UNFOLD)
    finally:
        op.execute("ALTER TABLE notifications FORCE ROW LEVEL SECURITY")
