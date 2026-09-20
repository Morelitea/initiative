/**
 * Everything connected to one thing.
 *
 * One request answers for every heading, so what is worth asserting is the
 * sorting: that a directional relation lands under the right one of its two
 * headings, that a heading with nothing under it is not drawn at all, and that a
 * link nobody asserted is not offered as one to take back.
 */
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse } from "msw";
import { describe, expect, it, vi } from "vitest";

import { buildSearchSuggestion } from "@/__tests__/factories";
import { guildHttp } from "@/__tests__/helpers/guildHttp";
import { server } from "@/__tests__/helpers/msw-server";
import { renderPage } from "@/__tests__/helpers/render";
import {
  type RelationshipRead,
  SearchEntityType,
  Tool,
} from "@/api/generated/initiativeAPI.schemas";

/**
 * Sigma draws the graph to a WebGL canvas, which jsdom has none of. The renderer
 * is stubbed so the rest of the picture — the controls around it, the region it
 * is drawn in, the key to its colours — is still the code under test. What the
 * canvas itself puts on screen is not a thing a DOM test can see either way.
 */
vi.mock("@react-sigma/core", () => ({
  SigmaContainer: ({ children }: { children?: React.ReactNode }) => (
    <div data-testid="sigma">{children}</div>
  ),
  useSigma: () => ({
    getGraph: () => ({
      order: 0,
      setNodeAttribute: () => {},
      removeNodeAttribute: () => {},
    }),
    viewportToGraph: () => ({ x: 0, y: 0 }),
  }),
  useRegisterEvents: () => () => {},
}));

// The WebGL machinery, stubbed at the seam rather than by faking a graphics
// card: these draw to a canvas, and a canvas draws nothing jsdom can be asked
// about.
vi.mock("@sigma/node-image", () => ({
  createNodeImageProgram: () => class {},
  NodeImageProgram: class {},
}));
vi.mock("sigma/utils", () => ({ animateNodes: () => () => {} }));
vi.mock("sigma/rendering", () => ({ drawDiscNodeLabel: () => {} }));

import { RelationsSection } from "./RelationsSection";

let nextId = 1;

/** Everything a far end of a link carries and none of these cases vary. */
const farEnd = {
  initiative_id: null,
  updated_at: null,
  tool: null,
  tool_id: null,
  tool_title: null,
  image_urls: [],
  icon: null,
  color: null,
  document_type: null,
  mime_type: null,
  original_filename: null,
  smart_link_url: null,
  is_open: null,
};

const row = (
  relationship_type: RelationshipRead["relationship_type"],
  direction: "inbound" | "outbound",
  title: string,
  provenance = "manual"
): RelationshipRead => ({
  id: nextId++,
  relationship_type,
  direction,
  provenance,
  confidence: null,
  created_by: 1,
  created_at: "2026-09-01T00:00:00Z",
  other: {
    ...farEnd,
    type: SearchEntityType.task,
    id: nextId,
    title,
    initiative_id: 3,
    tool: Tool.project,
    tool_id: 1,
  },
});

/** A dependency whose far end knows whether it is finished. */
const blocker = (title: string, isOpen: boolean): RelationshipRead => {
  const built = row("depends_on", "outbound", title);
  return { ...built, other: { ...built.other, is_open: isOpen } };
};

const tagEnd = { ...farEnd, type: SearchEntityType.tag, id: 99, title: "combat", color: "#ff0000" };

type Layout = "tiles" | "rows" | "carousel" | "graph";

/** The section itself, however this case has already answered the endpoint. */
const mount = (canEdit = true, defaultLayout: Layout = "tiles") =>
  renderPage(
    () => (
      <RelationsSection
        entity={{ type: SearchEntityType.task, id: 1 }}
        initiativeId={3}
        canEdit={canEdit}
        defaultLayout={defaultLayout}
      />
    ),
    { initialRoute: "/c/1" }
  );

const renderSection = (
  rows: RelationshipRead[],
  canEdit = true,
  defaultLayout: Layout = "tiles"
) => {
  server.use(guildHttp.get("/relationships/", () => HttpResponse.json(rows)));
  return mount(canEdit, defaultLayout);
};

/** The block a heading names, so a link can be asserted to be filed under it. */
const sectionNamed = async (name: string) =>
  (await screen.findByRole("heading", { name })).closest("section") as HTMLElement;

/** A label, which is fetched with everything else and drawn by no heading. */
const tagRow = (): RelationshipRead => ({
  ...row("tagged_with", "outbound", "combat"),
  other: { ...tagEnd },
});

describe("RelationsSection", () => {
  it("sorts the two sides of a dependency under their own headings", async () => {
    renderSection([
      row("depends_on", "outbound", "Waiting on this"),
      row("depends_on", "inbound", "Held up by me"),
    ]);

    const blockedBy = await sectionNamed("Blocked by");
    const blocks = await sectionNamed("Blocking");

    expect(within(blockedBy).getByText("Waiting on this")).toBeInTheDocument();
    expect(within(blocks).getByText("Held up by me")).toBeInTheDocument();
  });

  it("takes a symmetric link whichever way it runs", async () => {
    renderSection([row("attached", "inbound", "Attached from the far side")]);

    const attached = await sectionNamed("Attached");
    expect(within(attached).getByText("Attached from the far side")).toBeInTheDocument();
  });

  it("draws no heading for a relation nothing has", async () => {
    renderSection([row("attached", "outbound", "Only this")]);

    await screen.findByText("Only this");
    expect(screen.queryByRole("heading", { name: "Blocked by" })).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Part of" })).not.toBeInTheDocument();
  });

  // Counting the answer rather than what is drawn reported "some" over an
  // empty panel, because a label comes back with everything else and no
  // heading here draws it.
  it.each([
    ["nothing is connected", [] as RelationshipRead[]],
    ["nothing it shows is", [tagRow()]],
  ])("says so plainly when %s", async (_label, rows) => {
    renderSection(rows);

    expect(await screen.findByText(/Nothing linked yet\./)).toBeInTheDocument();
  });

  it("does not offer to unlink something read out of a body", async () => {
    // A `references` edge is withdrawn by editing the words that made it, so
    // there is nothing here to click.
    renderSection([row("references", "inbound", "A page that mentions this", "content")]);

    const section = await sectionNamed("Mentioned in");
    expect(within(section).getByText("A page that mentions this")).toBeInTheDocument();
    expect(
      within(section).queryByRole("button", { name: /A page that mentions this/ })
    ).not.toBeInTheDocument();
  });

  it("opens the add dialog on the thing, not on a classification", async () => {
    // Nobody opens this thinking "part_of". The picker is the only field until
    // something is picked, so the abstract question is never the price of entry.
    const user = userEvent.setup();
    renderSection([]);

    await user.click(await screen.findByRole("button", { name: "Add link" }));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByRole("combobox", { name: "Thing" })).toBeEnabled();
    expect(within(dialog).queryByLabelText("How the two relate")).not.toBeInTheDocument();
  });

  it("opens the way the surface asked, and offers the other ways", async () => {
    const user = userEvent.setup();
    renderSection([row("attached", "outbound", "Only this")], true, "rows");

    await screen.findByText("Only this");
    await user.click(screen.getByRole("button", { name: "How to show these" }));
    const menu = await screen.findByRole("menu");
    for (const name of ["Tiles", "List", "Carousel", "Graph"]) {
      expect(within(menu).getByRole("menuitem", { name })).toBeInTheDocument();
    }
  });

  it("shows one shelf in a carousel, with each link saying what it is", async () => {
    // No heading per kind of link: a carousel is pushed along, so what a link
    // says rides on its own card.
    renderSection(
      [row("attached", "outbound", "A brief"), row("depends_on", "outbound", "A blocker")],
      true,
      "carousel"
    );

    await screen.findByText("A brief");
    expect(screen.queryByRole("heading", { name: "Attached" })).not.toBeInTheDocument();
    expect(screen.getByText("Attached")).toBeInTheDocument();
    expect(screen.getByText("Blocked by")).toBeInTheDocument();
  });

  it("draws the picture with a key to what its colours mean", async () => {
    // The graph itself is a canvas, so what can be asserted here is the frame
    // around it: that it was drawn for these links, and that a reader is told
    // which colour is which.
    renderSection(
      [row("attached", "outbound", "A brief"), row("depends_on", "inbound", "Waiting on me")],
      true,
      "graph"
    );

    expect(await screen.findByRole("region", { name: /2 things/ })).toBeInTheDocument();
    expect(screen.getByText("Attached")).toBeInTheDocument();
    expect(screen.getByText("Blocking")).toBeInTheDocument();
    // Nothing it has no link of: a key listing every heading would say nothing.
    expect(screen.queryByText("Part of")).not.toBeInTheDocument();
  });

  it("walks further out when asked, and only then", async () => {
    // A second hop is a request per neighbour, so it is never paid for until
    // somebody asks for it.
    const user = userEvent.setup();
    const asked: string[] = [];
    server.use(
      guildHttp.get("/relationships/", ({ request }) => {
        const entity = new URL(request.url).searchParams.get("entity") ?? "";
        asked.push(entity);
        return HttpResponse.json(
          entity === "task:1" ? [row("attached", "outbound", "A brief")] : []
        );
      })
    );
    mount(true, "graph");

    await screen.findByRole("region", { name: /1 thing/ });
    expect(asked.filter((entity) => entity !== "task:1")).toHaveLength(0);

    await user.click(screen.getByRole("button", { name: "2 hops" }));
    await waitFor(() => expect(asked.some((entity) => entity !== "task:1")).toBe(true));
  });

  it("leaves labels out of the graph until asked, and out of the walk", async () => {
    // A tag is carried by everything that carries it, so walking through one
    // reaches most of the community in a hop. Filtering it when drawing would
    // still have paid for the walk.
    const user = userEvent.setup();
    renderSection([row("attached", "outbound", "A brief"), tagRow()], true, "graph");

    // One of the two links is a label, and it is not in the picture.
    expect(await screen.findByRole("region", { name: /1 thing/ })).toBeInTheDocument();
    expect(screen.queryByText("Tagged")).not.toBeInTheDocument();

    await user.click(screen.getByRole("checkbox", { name: "Show tags" }));
    expect(await screen.findByRole("region", { name: /2 things/ })).toBeInTheDocument();
    expect(screen.getByText("Tagged")).toBeInTheDocument();
  });

  it("says which project a link is in, when its name does not", async () => {
    // Six projects run from one template hold six tasks called "Do a thing".
    // The card has to say which, or it says nothing at all.
    const link = row("attached", "outbound", "Do a thing");
    renderSection([{ ...link, other: { ...link.other, tool_title: "Harvest" } }]);

    const section = await sectionNamed("Attached");
    expect(within(section).getByText(/Harvest/)).toBeInTheDocument();
  });

  it("says where each thing the picker offers lives", async () => {
    const user = userEvent.setup();
    // Two tasks of the same name, in different projects of one initiative.
    const offered = (entity_id: number, tool_id: number, tool_title: string) =>
      buildSearchSuggestion({
        entity_type: SearchEntityType.task,
        entity_id,
        title: "Do a thing",
        tool: Tool.project,
        tool_id,
        tool_title,
        initiative_id: 3,
        initiative_name: "Farmhands",
      });
    server.use(
      guildHttp.get("/search/recent", () =>
        HttpResponse.json([offered(11, 1, "Harvest"), offered(12, 2, "Winterhold")])
      )
    );
    renderSection([]);

    await user.click(await screen.findByRole("button", { name: "Add link" }));
    const dialog = await screen.findByRole("dialog");
    await user.click(within(dialog).getByRole("combobox", { name: "Thing" }));

    expect(await screen.findByText("Harvest")).toBeInTheDocument();
    expect(screen.getByText("Winterhold")).toBeInTheDocument();
    // The picker is already confined to one initiative, so naming it on every
    // row would be the same word twice over.
    expect(screen.queryByText(/Farmhands/)).not.toBeInTheDocument();
  });

  it("offers no way in at all to a reader who may not edit", async () => {
    renderSection([row("attached", "outbound", "Only this")], false);

    await screen.findByText("Only this");
    expect(screen.queryByRole("button", { name: "Add link" })).not.toBeInTheDocument();
  });

  it("says how far along a linked project is", async () => {
    // The card carries what the thing is doing now, not what it was called
    // when somebody linked it — so a project reads as its work.
    const built = row("attached", "outbound", "Marquee logistics");
    const project = {
      ...built,
      other: { ...built.other, type: SearchEntityType.project, id: 7 },
    };
    server.use(
      guildHttp.get("/smart-chips/", () =>
        HttpResponse.json({
          items: [
            {
              ref: "project:7:progress",
              entity_type: SearchEntityType.project,
              aspect: "progress",
              text: "1 / 3",
              title: null,
              tone: "neutral",
              color: null,
              date: null,
              number: null,
            },
          ],
        })
      )
    );
    renderSection([project]);

    expect(await screen.findByText("1 / 3")).toBeInTheDocument();
  });

  it("names itself after the thing it is about", async () => {
    // "Relations" is a word about the data model. A task has connections.
    renderSection([]);

    expect(await screen.findByRole("heading", { name: "Connections" })).toBeInTheDocument();
  });

  it("says how many blockers are still open, not how many there ever were", async () => {
    // A bare count outlives the work it describes, which is most of why the
    // heading stopped meaning anything.
    renderSection([blocker("Still going", true), blocker("Finished", false)]);

    const section = await sectionNamed("Blocked by");
    expect(within(section).getByText("1 of 2 still open")).toBeInTheDocument();
  });

  it("does not offer four ways of looking at nothing", async () => {
    renderSection([]);

    await screen.findByText(/Nothing linked yet\./);
    expect(screen.queryByRole("button", { name: "How to show these" })).not.toBeInTheDocument();
  });

  it("offers the ways of looking once there is something to look at", async () => {
    renderSection([row("attached", "outbound", "Something")]);

    await screen.findByText("Something");
    expect(screen.getByRole("button", { name: "How to show these" })).toBeInTheDocument();
  });

  it("writes the link out as a sentence naming both ends", async () => {
    const user = userEvent.setup();
    server.use(
      guildHttp.get("/search/recent", () =>
        HttpResponse.json([
          buildSearchSuggestion({
            entity_type: SearchEntityType.document,
            entity_id: 11,
            title: "Harvest",
            initiative_id: 3,
          }),
        ])
      )
    );
    renderSection([]);

    await user.click(await screen.findByRole("button", { name: "Add link" }));
    const dialog = await screen.findByRole("dialog");
    await user.click(within(dialog).getByRole("combobox", { name: "Thing" }));
    await user.click(await screen.findByText("Harvest"));

    // Both nouns are on screen, and the verb between them is a control.
    expect(within(dialog).getByText("This task")).toBeInTheDocument();
    const verb = within(dialog).getByRole("combobox", { name: "How the two relate" });
    // Never a dependency on somebody's behalf — that claim is theirs to make.
    expect(verb).not.toHaveTextContent("is blocked by");
  });
});
