/**
 * The wiki's page list, in the column the navigation drills into.
 *
 * What is worth asserting here is the disclosure: this column is a list of
 * PAGES, and a page's headings are what you ask for. So it starts closed, and
 * asking twice puts it back.
 */
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { buildWikiPage } from "@/__tests__/factories";
import { renderPage } from "@/__tests__/helpers/render";
import { WikiPageKind, type WikiPageSummary } from "@/api/generated/initiativeAPI.schemas";
import { SidebarProvider } from "@/components/ui/sidebar";

import { dropIntents, useWikiTreeExpansion, WikiPageTree } from "./WikiPageTree";

const page = buildWikiPage({
  id: 11,
  wiki_id: 3,
  title: "Step 1",
  slug: "step-1",
  headings: [{ text: "What to bring", level: 2, anchor: "what-to-bring" }],
});

const child = buildWikiPage({
  id: 12,
  wiki_id: 3,
  parent_page_id: 11,
  title: "What it costs",
  slug: "what-it-costs",
});

const setup = (pages = [page], activePageId = 11) =>
  renderPage(
    () => (
      <SidebarProvider>
        <WikiPageTree
          pages={pages}
          activePageId={activePageId}
          homePageId={null}
          hrefOf={() => "/page"}
        />
      </SidebarProvider>
    ),
    { initialRoute: "/wiki" }
  );

describe("the page list's disclosure", () => {
  it("starts closed, opens when asked, and closes again", async () => {
    const user = userEvent.setup();
    setup();

    await screen.findByText("Step 1");
    expect(screen.queryByText("What to bring")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Expand" }));
    expect(await screen.findByText("What to bring")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Collapse" }));
    expect(screen.queryByText("What to bring")).not.toBeInTheDocument();
  });
});

describe("pages filed under pages", () => {
  it("draws a sub-page inside the page it is filed under, once that is opened", async () => {
    const user = userEvent.setup();
    setup([page, child]);

    await screen.findByText("Step 1");
    // Closed to start with, like everything else in this column.
    expect(screen.queryByText("What it costs")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Expand" }));

    // What is ON the page, and then what is filed UNDER it.
    expect(await screen.findByText("What to bring")).toBeInTheDocument();
    expect(screen.getByText("What it costs")).toBeInTheDocument();
  });
});

describe("opening and closing the whole tree at once", () => {
  /** A tree driven by the caller's expansion, the way the sidebar drives it. */
  const Driven = ({ pages }: { pages: WikiPageSummary[] }) => {
    const expansion = useWikiTreeExpansion(pages);
    return (
      <SidebarProvider>
        <button type="button" onClick={expansion.toggleAll}>
          {expansion.allOpen ? "close all" : "open all"}
        </button>
        <WikiPageTree
          pages={pages}
          activePageId={null}
          homePageId={null}
          hrefOf={() => "/page"}
          expansion={expansion}
        />
      </SidebarProvider>
    );
  };

  it("opens every row that has something inside it, and closes them again", async () => {
    const user = userEvent.setup();
    renderPage(() => <Driven pages={[page, child]} />, { initialRoute: "/wiki" });

    await screen.findByText("Step 1");
    expect(screen.queryByText("What it costs")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "open all" }));
    // Both of what a disclosure opens: the headings on the page, and what is
    // filed under it.
    expect(await screen.findByText("What to bring")).toBeInTheDocument();
    expect(screen.getByText("What it costs")).toBeInTheDocument();

    // Now everything is open, so the control offers the other direction.
    await user.click(screen.getByRole("button", { name: "close all" }));
    expect(screen.queryByText("What it costs")).not.toBeInTheDocument();
    expect(screen.queryByText("What to bring")).not.toBeInTheDocument();
  });

  it("reports nothing to act on when no page holds anything", async () => {
    // What the sidebar reads to leave the control out rather than offering a
    // button that would do nothing.
    const flat = buildWikiPage({ id: 20, wiki_id: 3, title: "Just this", headings: [] });
    const Probe = () => {
      const expansion = useWikiTreeExpansion([flat]);
      return <p>{expansion.isEmpty ? "nothing to open" : "something to open"}</p>;
    };
    renderPage(() => <Probe />, { initialRoute: "/wiki" });

    expect(await screen.findByText("nothing to open")).toBeInTheDocument();
  });
});

describe("arriving at a page that is filed inside something", () => {
  it("opens what it is filed inside, so the column shows where you are", async () => {
    setup([page, child], 12);

    // The branch was closed; landing in it is what opened it.
    expect(await screen.findByText("What it costs")).toBeInTheDocument();
  });

  it("leaves a page at the top of the wiki closed", async () => {
    setup([page, child], 11);

    await screen.findByText("Step 1");
    expect(screen.queryByText("What it costs")).not.toBeInTheDocument();
  });
});

describe("what a drag may land on", () => {
  const none = new Set<number>();
  const asPage = { id: 11, kind: WikiPageKind.page, parent_page_id: null };
  const nestedPage = { id: 12, kind: WikiPageKind.page, parent_page_id: 11 };
  const borrowed = { id: 7, kind: WikiPageKind.document, parent_page_id: null };

  it("offers a borrowed document nowhere inside a branch", () => {
    // The wiki cannot file a document under one of its pages, so the branch
    // does not answer rather than appearing to take it.
    expect(dropIntents(borrowed, nestedPage, none)).toEqual([]);
  });

  it("offers a borrowed document the edges of a page at the top", () => {
    expect(dropIntents(borrowed, asPage, none)).toEqual(["before", "after"]);
  });

  it("offers a page the middle of another page, and only the edges of a document", () => {
    expect(dropIntents(asPage, nestedPage, none)).toEqual(["before", "into", "after"]);
    expect(dropIntents(asPage, borrowed, none)).toEqual(["before", "after"]);
  });

  it("offers a page nothing on itself or on what is filed under it", () => {
    expect(dropIntents(asPage, asPage, none)).toEqual([]);
    expect(dropIntents(asPage, nestedPage, new Set([12]))).toEqual([]);
  });
});
