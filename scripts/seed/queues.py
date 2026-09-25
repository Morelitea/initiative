"""Queues: turn orders, with who is up and who is still hidden."""

from __future__ import annotations

from app.core.tools import Tool
from app.models.tenant.queue import Queue, QueueItem
from app.models.tenant.resource_grant import ResourceAccessLevel

from seed.common import Community, share, tag

#: Each queue, shared the way ``share`` reads it. An item's ``user`` links it
#: to a person; ``active_item_label`` is whose turn it is.
QUEUES: dict[str, list[dict]] = {
    "primary": [
        {
            "name": "Death House Encounter",
            "initiative": "strahd",
            "description": "Combat encounter in the haunted Death House basement",
            "created_by": "Dungeon Master",
            "is_active": True,
            "current_round": 3,
            "writers": ["Thorn Ironforge", "Elara Moonwhisper"],
            "readers": ["Vex Shadowstep", "Seraphina Dawnlight"],
            "active_item_label": "Thorn Ironforge",
            "items": [
                {
                    "label": "Thorn Ironforge",
                    "position": 22,
                    "user": "Thorn Ironforge",
                    "color": "#DC2626",
                    "notes": "Raging — advantage on Str checks",
                    "tags": ["combat"],
                },
                {
                    "label": "Elara Moonwhisper",
                    "position": 19,
                    "user": "Elara Moonwhisper",
                    "color": "#3B82F6",
                    "notes": "Concentration: Spirit Guardians",
                    "tags": ["combat"],
                },
                {
                    "label": "Shambling Mound",
                    "position": 17,
                    "color": "#10B981",
                    "notes": "HP: 136/136",
                    "tags": ["combat", "boss fight"],
                },
                {
                    "label": "Vex Shadowstep",
                    "position": 16,
                    "user": "Vex Shadowstep",
                    "color": "#8B5CF6",
                    "notes": "Hidden — bonus action stealth",
                    "tags": ["combat"],
                },
                {
                    "label": "Seraphina Dawnlight",
                    "position": 12,
                    "user": "Seraphina Dawnlight",
                    "color": "#F59E0B",
                    "tags": ["combat"],
                },
                {
                    "label": "Shadow #1",
                    "position": 9,
                    "color": "#374151",
                    "notes": "HP: 16/16",
                },
                {
                    "label": "Shadow #2",
                    "position": 5,
                    "color": "#374151",
                    "notes": "HP: 16/16",
                },
                {
                    "label": "Shadow #3",
                    "position": 3,
                    "color": "#374151",
                    "is_visible": False,
                    "notes": "Surprise round — not yet revealed",
                },
            ],
        },
        {
            "name": "Vallaki Town Square Ambush",
            "initiative": "strahd",
            "description": "Strahd's wolves attack during the Festival of the Blazing Sun",
            "created_by": "Dungeon Master",
            "is_active": False,
            "current_round": 1,
            "writers": ["Thorn Ironforge"],
            "roles": [("strahd", ResourceAccessLevel.read)],
            "items": [
                {
                    "label": "Dire Wolf Alpha",
                    "position": 20,
                    "color": "#6B7280",
                    "notes": "Pack leader — AC 14, HP: 37",
                    "tags": ["combat"],
                },
                {
                    "label": "Thorn Ironforge",
                    "position": 18,
                    "user": "Thorn Ironforge",
                    "color": "#DC2626",
                },
                {
                    "label": "Elara Moonwhisper",
                    "position": 15,
                    "user": "Elara Moonwhisper",
                    "color": "#3B82F6",
                },
                {
                    "label": "Wolf Pack (x4)",
                    "position": 13,
                    "color": "#9CA3AF",
                    "notes": "HP: 11 each",
                },
                {
                    "label": "Vex Shadowstep",
                    "position": 11,
                    "user": "Vex Shadowstep",
                    "color": "#8B5CF6",
                },
                {
                    "label": "Seraphina Dawnlight",
                    "position": 8,
                    "user": "Seraphina Dawnlight",
                    "color": "#F59E0B",
                },
            ],
        },
        {
            "name": "Cragmaw Hideout Assault",
            "initiative": "lmop",
            "description": "The party storms the goblin cave to rescue Sildar Hallwinter",
            "created_by": "Admin User",
            "is_active": False,
            "current_round": 5,
            "writers": ["Dungeon Master", "Thorn Ironforge", "Elara Moonwhisper"],
            "general": ResourceAccessLevel.read,
            "items": [
                {
                    "label": "Admin User (Ranger)",
                    "position": 21,
                    "user": "Admin User",
                    "color": "#059669",
                    "notes": "Hunter's Mark on Klarg",
                },
                {
                    "label": "Thorn Ironforge",
                    "position": 18,
                    "user": "Thorn Ironforge",
                    "color": "#DC2626",
                },
                {
                    "label": "Klarg the Bugbear",
                    "position": 15,
                    "color": "#B91C1C",
                    "notes": "HP: 27/27 — boss",
                    "tags": ["combat", "boss fight"],
                },
                {
                    "label": "Elara Moonwhisper",
                    "position": 14,
                    "user": "Elara Moonwhisper",
                    "color": "#3B82F6",
                },
                {
                    "label": "Goblin Archer #1",
                    "position": 10,
                    "color": "#65A30D",
                    "notes": "HP: 7/7",
                },
                {
                    "label": "Goblin Archer #2",
                    "position": 7,
                    "color": "#65A30D",
                    "notes": "HP: 7/7",
                },
                {
                    "label": "Ripper (Wolf)",
                    "position": 4,
                    "color": "#78716C",
                    "notes": "HP: 11/11 — Klarg's pet",
                },
            ],
        },
    ],
    "starforge": [
        {
            "name": "Bridge Standoff: Krellix Boarding Party",
            "initiative": "starfall",
            "description": "The Krellix shock troopers have breached the main airlock",
            "created_by": "Admin User",
            "is_active": True,
            "current_round": 2,
            "writers": ["Finley Goldtongue", "Kael Windrunner"],
            "readers": ["Vex Shadowstep"],
            "general": ResourceAccessLevel.read,
            "active_item_label": "Krellix Shock Trooper #1",
            "items": [
                {
                    "label": "Kael Windrunner",
                    "position": 24,
                    "user": "Kael Windrunner",
                    "color": "#0EA5E9",
                    "notes": "Shield generator overcharged — +2 AC",
                },
                {
                    "label": "Krellix Shock Trooper #1",
                    "position": 21,
                    "color": "#EF4444",
                    "notes": "HP: 45/45 — plasma rifle",
                    "tags": ["combat"],
                },
                {
                    "label": "Aurelia Brightshield",
                    "position": 19,
                    "user": "Aurelia Brightshield",
                    "color": "#F59E0B",
                },
                {
                    "label": "Krellix Shock Trooper #2",
                    "position": 17,
                    "color": "#EF4444",
                    "notes": "HP: 45/45",
                },
                {
                    "label": "Finley Goldtongue",
                    "position": 15,
                    "user": "Finley Goldtongue",
                    "color": "#8B5CF6",
                    "notes": "Attempting to hack the airlock controls",
                },
                {
                    "label": "Vex Shadowstep",
                    "position": 12,
                    "user": "Vex Shadowstep",
                    "color": "#6366F1",
                },
                {
                    "label": "Krellix Commander",
                    "position": 10,
                    "color": "#B91C1C",
                    "notes": "HP: 80/80 — energy blade",
                    "tags": ["combat"],
                },
            ],
        }
    ],
    "tides": [
        {
            "name": "Kraken Attack on the Crimson Maiden",
            "initiative": "crimson",
            "description": "A massive kraken surfaces and wraps its tentacles around the ship",
            "created_by": "Finley Goldtongue",
            "is_active": True,
            "current_round": 4,
            "writers": ["Admin User", "Dungeon Master", "Thorn Ironforge"],
            "active_item_label": "Finley Goldtongue",
            "items": [
                {
                    "label": "Finley Goldtongue",
                    "position": 23,
                    "user": "Finley Goldtongue",
                    "color": "#F59E0B",
                    "notes": "At the helm — trying to steer free",
                },
                {
                    "label": "Kraken Tentacle (Port)",
                    "position": 20,
                    "color": "#7C3AED",
                    "notes": "HP: 30/30 — grappling the mast",
                },
                {
                    "label": "Thorn Ironforge",
                    "position": 19,
                    "user": "Thorn Ironforge",
                    "color": "#DC2626",
                    "notes": "Hacking at the starboard tentacle",
                },
                {
                    "label": "Kraken Tentacle (Starboard)",
                    "position": 18,
                    "color": "#7C3AED",
                    "notes": "HP: 30/30",
                },
                {
                    "label": "Kael Windrunner",
                    "position": 16,
                    "user": "Kael Windrunner",
                    "color": "#0EA5E9",
                    "notes": "In the crow's nest — firing arrows",
                },
                {
                    "label": "Admin User (First Mate)",
                    "position": 14,
                    "user": "Admin User",
                    "color": "#059669",
                },
                {
                    "label": "Aurelia Brightshield",
                    "position": 11,
                    "user": "Aurelia Brightshield",
                    "color": "#EAB308",
                    "notes": "Channeling Tide Mother's blessing",
                },
                {
                    "label": "Seraphina Dawnlight",
                    "position": 8,
                    "user": "Seraphina Dawnlight",
                    "color": "#EC4899",
                },
                {
                    "label": "Kraken (Body)",
                    "position": 5,
                    "color": "#581C87",
                    "notes": "HP: 200/200 — submerged, surfaces round 6",
                    "is_visible": False,
                    "tags": ["boss fight"],
                },
            ],
        },
        {
            "name": "Port Havoc Bar Brawl",
            "initiative": "crimson",
            "description": "A tavern argument escalates into a full-blown melee",
            "created_by": "Dungeon Master",
            "is_active": False,
            "current_round": 1,
            "writers": ["Finley Goldtongue"],
            "general": ResourceAccessLevel.read,
            "items": [
                {
                    "label": "Finley Goldtongue",
                    "position": 19,
                    "user": "Finley Goldtongue",
                    "color": "#F59E0B",
                },
                {
                    "label": "Thorn Ironforge",
                    "position": 17,
                    "user": "Thorn Ironforge",
                    "color": "#DC2626",
                },
                {
                    "label": "Rival Pirate Captain",
                    "position": 15,
                    "color": "#B91C1C",
                    "notes": "Dual-wielding cutlasses",
                },
                {
                    "label": "Rival Crew (x3)",
                    "position": 12,
                    "color": "#9CA3AF",
                    "notes": "HP: 9 each",
                },
                {
                    "label": "Kael Windrunner",
                    "position": 10,
                    "user": "Kael Windrunner",
                    "color": "#0EA5E9",
                },
                {
                    "label": "Barkeep (Non-combatant)",
                    "position": 1,
                    "color": "#78716C",
                    "notes": "Hiding behind the bar",
                },
            ],
        },
    ],
}


async def seed(c: Community) -> None:
    for d in QUEUES[c.key]:
        creator = c.users[d["created_by"]]
        queue = Queue(
            initiative_id=c.initiatives[d["initiative"]].id,
            name=d["name"],
            description=d.get("description"),
            created_by=creator.id,
            is_active=d.get("is_active", False),
            current_round=d.get("current_round", 1),
        )
        c.session.add(queue)
        await c.session.flush()
        c.ids["queues"].append(queue.id)
        share(
            c,
            Tool.queue,
            queue,
            creator,
            writers=d.get("writers", ()),
            readers=d.get("readers", ()),
            roles=d.get("roles", ()),
            general=d.get("general"),
        )
        for item in d["items"]:
            row = QueueItem(
                queue_id=queue.id,
                label=item["label"],
                position=item.get("position", 0),
                user_id=c.users[item["user"]].id if "user" in item else None,
                color=item.get("color"),
                notes=item.get("notes"),
                is_visible=item.get("is_visible", True),
            )
            c.session.add(row)
            await c.session.flush()
            c.ids["queue_items"].append(row.id)
            tag(c, row, item.get("tags", ()))
            if row.label == d.get("active_item_label"):
                queue.current_item_id = row.id
        c.session.add(queue)
        await c.session.flush()
