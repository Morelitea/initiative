import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse } from "msw";
import { describe, expect, it } from "vitest";

import { buildDocumentSummary } from "@/__tests__/factories";
import { guildHttp } from "@/__tests__/helpers/guildHttp";
import { server } from "@/__tests__/helpers/msw-server";
import { createTestQueryClient, renderPage } from "@/__tests__/helpers/render";
import type { DocumentSummary } from "@/api/generated/initiativeAPI.schemas";
import { VIEW_PREFERENCES_QUERY_KEY } from "@/hooks/useViewPreference";

import { DocumentsView } from "./DocumentsPage";

const INITIATIVE_ID = 1;

/**
 * Render in list view: the tags view routes its tag filtering through the tree
 * sidebar, and the type select plus the documents/templates toggle are what
 * these tests drive.
 */
function renderDocuments() {
  const queryClient = createTestQueryClient();
  queryClient.setQueryData(VIEW_PREFERENCES_QUERY_KEY, {
    items: { "documents:view-mode": "list" },
  });
  const Page = () => <DocumentsView fixedInitiativeId={INITIATIVE_ID} canCreate={false} />;
  return renderPage(Page, { queryClient });
}

/** Capture every documents list request and serve `items` back. */
function stubDocuments(items: DocumentSummary[] = []) {
  const requests: URLSearchParams[] = [];
  server.use(
    guildHttp.get("/documents/", ({ request }) => {
      requests.push(new URL(request.url).searchParams);
      return HttpResponse.json({
        items,
        total_count: items.length,
        page: 1,
        page_size: 20,
        has_next: false,
        sort_by: null,
        sort_dir: null,
      });
    }),
    guildHttp.get("/documents/counts", ({ request }) => {
      const params = new URL(request.url).searchParams;
      return HttpResponse.json({
        // Distinct totals so the toggle's two badges are told apart.
        total_count: params.get("is_template") === "true" ? 2 : 7,
        untagged_count: 0,
        tag_counts: {},
      });
    })
  );
  return requests;
}

const latest = (requests: URLSearchParams[]) => requests[requests.length - 1];

describe("DocumentsView document type filter", () => {
  it("omits the type filter until one is chosen", async () => {
    const requests = stubDocuments();
    renderDocuments();

    await waitFor(() => expect(requests.length).toBeGreaterThan(0));
    expect(latest(requests).get("document_type")).toBeNull();
  });

  it("narrows the query by document type", async () => {
    const user = userEvent.setup();
    const requests = stubDocuments();
    renderDocuments();
    await waitFor(() => expect(requests.length).toBeGreaterThan(0));

    await user.click(await screen.findByRole("button", { name: /filters/i }));
    await user.click(screen.getByRole("combobox", { name: /filter by type/i }));
    await user.click(screen.getByRole("option", { name: "Whiteboard" }));

    await waitFor(() => expect(latest(requests).get("document_type")).toBe("whiteboard"));
    // The type filter narrows within the state being shown, not across it.
    expect(latest(requests).get("is_template")).toBe("false");
    expect(
      await screen.findByRole("button", { name: /filters \(1 active\)/i })
    ).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /clear all/i }));
    await waitFor(() => expect(latest(requests).get("document_type")).toBeNull());
  });
});

describe("DocumentsView remembered sort", () => {
  it("opens newest-first and remembers a different sort for the next visit", async () => {
    const user = userEvent.setup();
    // The table only renders once the list has something in it.
    const requests = stubDocuments([buildDocumentSummary({ initiative_id: INITIATIVE_ID })]);
    const first = renderDocuments();

    await waitFor(() => expect(requests.length).toBeGreaterThan(0));
    expect(latest(requests).get("sort_by")).toBe("updated_at");
    expect(latest(requests).get("sort_dir")).toBe("desc");

    await user.click(await screen.findByRole("button", { name: /title/i }));
    await waitFor(() => expect(latest(requests).get("sort_by")).toBe("name"));
    expect(latest(requests).get("sort_dir")).toBe("asc");

    // The next visit asks the server for the same order it was left in.
    first.unmount();
    requests.length = 0;
    renderDocuments();
    await waitFor(() => expect(requests.length).toBeGreaterThan(0));
    expect(latest(requests).get("sort_by")).toBe("name");
    expect(latest(requests).get("sort_dir")).toBe("asc");
  });
});

describe("DocumentsView documents/templates states", () => {
  it("lists documents by default and templates when toggled", async () => {
    const user = userEvent.setup();
    const requests = stubDocuments();
    renderDocuments();

    await waitFor(() => expect(requests.length).toBeGreaterThan(0));
    expect(latest(requests).get("is_template")).toBe("false");

    await user.click(await screen.findByRole("radio", { name: "Templates" }));
    await waitFor(() => expect(latest(requests).get("is_template")).toBe("true"));

    await user.click(screen.getByRole("radio", { name: "Documents" }));
    await waitFor(() => expect(latest(requests).get("is_template")).toBe("false"));
  });

  it("badges each state with its own total", async () => {
    stubDocuments();
    renderDocuments();

    expect(await screen.findByRole("radio", { name: "Documents" })).toHaveTextContent("7");
    expect(await screen.findByRole("radio", { name: "Templates" })).toHaveTextContent("2");
  });

  it("offers no create action in the empty templates state", async () => {
    const user = userEvent.setup();
    stubDocuments();
    renderDocuments();

    await user.click(await screen.findByRole("radio", { name: "Templates" }));

    expect(await screen.findByText("No templates yet")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Start writing" })).not.toBeInTheDocument();
  });
});
