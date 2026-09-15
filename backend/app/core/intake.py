"""The intake streams: what kinds of work arrive, and what feeds each one.

A **stream** is a named kind of operations work — security, moderation,
support, feedback. It is code rather than configuration because *its sources
are code*: what feeds ``security`` is a set of rules that watch the running
system, and what feeds ``moderation`` is a report endpoint. Adding a stream is
a release, exactly as adding an ``AuditEventType`` or a ``Tool`` is, and for
the same reason — one registry drives every surface.

A **binding** is the data half: *this stream, in this guild, lands in that
project.* Bindings live in the guild schema (``intake_bindings``); the
platform's pointer to the guild that holds them is
``app_settings.operations_guild_id``.

Nothing here names a company or a deployment. A deployment that has bound no
stream shows none of these surfaces and every writer call is a no-op.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class IntakeStream(str, Enum):
    """The kinds of operations work a deployment can route into a project."""

    security = "security"
    moderation = "moderation"
    support = "support"
    feedback = "feedback"


class Source(str, Enum):
    """Where a case in a stream comes from."""

    #: A rule watching the running system decided a line was crossed.
    alerted = "alerted"
    #: A signed-in person sent it to us.
    submitted = "submitted"
    #: Somebody opened the task by hand, in the project, like any other task.
    manual = "manual"


class Submitter(str, Enum):
    """Who the writer acts for when a case is opened."""

    system = "system"
    member = "member"


@dataclass(frozen=True)
class IntakeStreamMeta:
    """What a stream is fed by, and the blueprint that sets its project up."""

    sources: frozenset[Source]
    submitter: Submitter
    #: Filename under ``app/blueprints/intake/`` holding the export envelope
    #: that "set this up for me" imports.
    blueprint: str


#: Every stream, declared once. ``intake_test`` holds the enum and this map in
#: step, so a stream cannot exist without saying what feeds it.
STREAMS: dict[IntakeStream, IntakeStreamMeta] = {
    IntakeStream.security: IntakeStreamMeta(
        sources=frozenset({Source.alerted, Source.manual}),
        submitter=Submitter.system,
        blueprint="security.json",
    ),
    IntakeStream.moderation: IntakeStreamMeta(
        sources=frozenset({Source.submitted, Source.manual}),
        submitter=Submitter.member,
        blueprint="moderation.json",
    ),
    IntakeStream.support: IntakeStreamMeta(
        sources=frozenset({Source.submitted, Source.manual}),
        submitter=Submitter.member,
        blueprint="support.json",
    ),
    IntakeStream.feedback: IntakeStreamMeta(
        sources=frozenset({Source.submitted, Source.manual}),
        submitter=Submitter.member,
        blueprint="feedback.json",
    ),
}


def meta(stream: IntakeStream) -> IntakeStreamMeta:
    """What feeds ``stream``. Raises for a stream with no declaration."""
    return STREAMS[stream]


class CaseField(str, Enum):
    """The named fields a case carries besides its title and body.

    Each is a **property** on the task rather than a column, so a stream grows
    a field without a migration, and the project a team restructures keeps
    them. The writer fills the ones it has values for and leaves the rest
    empty.
    """

    #: Who the case is about, as the weak integer ref the audit envelope uses.
    #: A number rather than a person-picker: the subject of a case is not a
    #: member of the initiative handling it, and an erased account should leave
    #: a dangling id rather than a preserved person.
    subject_user = "subject_user"
    #: Which guild the case is about, same weak-ref reasoning.
    subject_guild = "subject_guild"
    #: The audit event this case was projected from, by uuid. What makes the
    #: population defensible: every case traces back to a row.
    source_event = "source_event"
    #: What the case is about, when it is about one thing in particular.
    resource_type = "resource_type"
    resource_id = "resource_id"
    #: When the thing happened, as distinct from when the case was filed.
    reported_at = "reported_at"
    #: Free text the stream's own project decides the vocabulary of.
    severity = "severity"
    #: The key of the finding in the private security repository, written in by
    #: a person when a case turns out to need a code change. One-way, by hand.
    tracker_key = "tracker_key"


#: Each field's property type, as a ``PropertyType`` value. Declared as plain
#: strings so this module stays free of model imports; ``intake_test`` checks
#: every one against the real enum, and against what the blueprints declare.
CASE_FIELD_TYPES: dict[CaseField, str] = {
    CaseField.subject_user: "number",
    CaseField.subject_guild: "number",
    CaseField.source_event: "text",
    CaseField.resource_type: "text",
    CaseField.resource_id: "number",
    CaseField.reported_at: "datetime",
    CaseField.severity: "text",
    CaseField.tracker_key: "text",
}

#: Which fields each stream's blueprint defines. ``tracker_key`` is security's
#: alone — it names a finding in the private repository, which is a thing only
#: a security case becomes.
STREAM_FIELDS: dict[IntakeStream, tuple[CaseField, ...]] = {
    IntakeStream.security: (
        CaseField.subject_user,
        CaseField.subject_guild,
        CaseField.source_event,
        CaseField.severity,
        CaseField.reported_at,
        CaseField.tracker_key,
    ),
    IntakeStream.moderation: (
        CaseField.subject_user,
        CaseField.subject_guild,
        CaseField.resource_type,
        CaseField.resource_id,
        CaseField.severity,
        CaseField.reported_at,
    ),
    IntakeStream.support: (
        CaseField.subject_user,
        CaseField.subject_guild,
        CaseField.reported_at,
    ),
    IntakeStream.feedback: (
        CaseField.subject_user,
        CaseField.subject_guild,
        CaseField.reported_at,
    ),
}
