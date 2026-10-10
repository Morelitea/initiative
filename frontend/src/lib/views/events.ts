import { at, itemPageKind, type Region } from "./itemPage";
import type { ViewNode } from "./tree";

const field = (id: string): ViewNode => ({ type: "field", props: { field: id } });

/**
 * An event's page as shipped: its title and what else can be done with it
 * across the top; what it is and who is coming in the main column; and when
 * and where it is, with its tags and properties, beside them. On one column
 * it reads as the event page always has: the description, when and where,
 * your answer, who is coming, tags, relations, then properties.
 */
const EVENT_PAGE_REGIONS: Record<Region, ViewNode[]> = {
  header: [
    {
      type: "stack",
      props: { direction: "row", gap: "sm", align: "start" },
      children: [field("title"), { type: "actions" }],
    },
    { type: "notice" },
  ],
  main: [
    at(1, { type: "section", children: [field("description")] }),
    at(3, { type: "rsvp" }),
    at(4, { type: "section", children: [field("attendees")] }),
    at(6, { type: "relations" }),
  ],
  side: [
    at(2, {
      type: "section",
      children: [{ type: "dates" }, field("recurrence"), field("location")],
    }),
    at(5, { type: "section", children: [field("tags")] }),
    at(7, { type: "section", children: [{ type: "properties" }] }),
  ],
};

/** An event's page: its dates and properties edit fields as a field does. */
export const EVENT_PAGE_KIND = itemPageKind({
  shipped: EVENT_PAGE_REGIONS,
  fieldParts: ["field", "dates", "properties"],
  moreOrder: 8,
});
