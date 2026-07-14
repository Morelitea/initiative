"""Custom-property serialization for export envelopes.

One flat, by-NAME encoding shared by every envelope that carries properties
(events, documents — and the project envelope's task values use the same
type→field rules via its own pydantic model), so a future import reads them
all with one rule set:

- text/url/select  → ``value_text``
- number           → ``value_number``
- checkbox         → ``value_boolean``
- date/datetime    → ``value_text`` (ISO 8601)
- multi_select     → ``value_json``
- user_reference   → ``value_email``

Works on any ``*PropertyValue`` model (task/document/calendar-event) — they
share the value columns and the ``property_definition``/``value_user``
relationships, which callers must have eager-loaded.
"""

from __future__ import annotations


def property_export_dict(pv) -> dict:
    prop = pv.property_definition
    prop_type = prop.type.value if hasattr(prop.type, "value") else str(prop.type)
    record: dict = {"property_name": prop.name, "property_type": prop_type}
    if prop_type in ("text", "url", "select"):
        record["value_text"] = pv.value_text
    elif prop_type == "number":
        record["value_number"] = (
            float(pv.value_number) if pv.value_number is not None else None
        )
    elif prop_type == "checkbox":
        record["value_boolean"] = pv.value_boolean
    elif prop_type == "date":
        record["value_text"] = pv.value_date.isoformat() if pv.value_date else None
    elif prop_type == "datetime":
        record["value_text"] = (
            pv.value_datetime.isoformat() if pv.value_datetime else None
        )
    elif prop_type == "multi_select":
        record["value_json"] = pv.value_json
    elif prop_type == "user_reference":
        record["value_email"] = pv.value_user.email if pv.value_user else None
    return record
