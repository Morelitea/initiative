import { ListingKind } from "@/api/generated/initiativeAPI.schemas";

/**
 * Which marketplace offers a listing.
 *
 * Every kind but one installs to a **community** — a dashboard lands in an
 * initiative, an app mounts in a community, and installing is something a
 * community's admins do. A profile pack installs to a **person**: its
 * decorations land in one account's library and belong to that person across
 * every community they are in.
 *
 * That is why there are two marketplaces rather than one with a filter. They
 * have different shelves, different buyers and different answers to "do I
 * already have this" — a community's install is shared, a person's is theirs.
 *
 * Mirrors ``KIND_AUDIENCE`` in ``backend/app/services/marketplace/
 * definitions.py``, which is the source of truth; a kind missing from both
 * lists here is offered by neither, which the test below refuses.
 */
export const USER_SHELVES: readonly ListingKind[] = [ListingKind.profile_pack];

export const COMMUNITY_SHELVES: readonly ListingKind[] = [
  ListingKind.dashboard,
  ListingKind.app,
  ListingKind.auto,
];

/** Whether this kind is bought by a person rather than by a community. */
export const isUserShelf = (kind: ListingKind): boolean => USER_SHELVES.includes(kind);
