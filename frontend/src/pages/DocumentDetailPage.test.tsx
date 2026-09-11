import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse } from "msw";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { buildDocumentSummary } from "@/__tests__/factories";
import { guildHttp } from "@/__tests__/helpers/guildHttp";
import { server } from "@/__tests__/helpers/msw-server";
import { renderPage } from "@/__tests__/helpers/render";

const collaborating = { value: false };

vi.mock("@/hooks/useCollaboration", () => ({
  useCollaboration: () => ({
    providerFactory: null,
    connectionStatus: collaborating.value ? "connected" : "disconnected",
    isSynced: collaborating.value,
    collaborators: [],
    collaboratorsReady: collaborating.value,
    isCollaborating: collaborating.value,
    isReady: true,
    connect: vi.fn(),
    resume: vi.fn(),
    disconnect: vi.fn(),
    sendContent: vi.fn(),
  }),
}));

vi.mock("@/components/documents/editor/editor", () => ({
  Editor: () => <div data-testid="editor" />,
}));

const doc = buildDocumentSummary({ id: 7, name: "Original", initiative_id: 1 });

const patches: Record<string, unknown>[] = [];

beforeEach(() => {
  patches.length = 0;
  collaborating.value = false;
  server.use(
    guildHttp.get("/documents/:documentId", () => HttpResponse.json(doc)),
    guildHttp.patch("/documents/:documentId", async ({ request }) => {
      const body = (await request.json()) as Record<string, unknown>;
      patches.push(body);
      return HttpResponse.json({ ...doc, name: body.name ?? doc.name });
    }),
    guildHttp.post("/recents/", () => HttpResponse.json({})),
    guildHttp.get("/documents/:documentId/backlinks", () => HttpResponse.json([])),
    guildHttp.get("/properties/definitions", () => HttpResponse.json([]))
  );
});

const { DocumentDetailPage } = await import("./DocumentDetailPage");

const renderDoc = () =>
  renderPage(DocumentDetailPage, {
    initialRoute: "/g/$guildId/i/$initiativeId/documents/$documentId",
    routeParams: { guildId: "1", initiativeId: "1", documentId: "7" },
  });

describe("renaming a document", () => {
  it("keeps the Save button beside the field while the name is being typed", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    renderDoc();

    const input = await screen.findByDisplayValue("Original");
    await user.clear(input);
    await user.type(input, "Renamed");

    // Well past the autosave debounce, with the field still held.
    await vi.advanceTimersByTimeAsync(6000);

    expect(patches).toEqual([]);
    expect(screen.getByRole("button", { name: "Save" })).not.toBeDisabled();

    await user.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(patches).toHaveLength(1));
    expect(patches[0]).toMatchObject({ name: "Renamed" });
    vi.useRealTimers();
  });

  it("autosaves the name once the field is let go", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    renderDoc();

    const input = await screen.findByDisplayValue("Original");
    await user.clear(input);
    await user.type(input, "Renamed");
    await user.tab();

    await vi.advanceTimersByTimeAsync(3000);

    await waitFor(() => expect(patches).toHaveLength(1));
    expect(patches[0]).toMatchObject({ name: "Renamed" });
    vi.useRealTimers();
  });

  it("does not PATCH on a loop while collaborating with nothing edited", async () => {
    collaborating.value = true;
    vi.useFakeTimers({ shouldAdvanceTime: true });
    renderDoc();
    await screen.findByDisplayValue("Original");

    await vi.advanceTimersByTimeAsync(45_000);

    expect(patches).toEqual([]);
    vi.useRealTimers();
  });

  it("still autosaves a rename while collaborating", async () => {
    collaborating.value = true;
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    renderDoc();

    const input = await screen.findByDisplayValue("Original");
    await user.clear(input);
    await user.type(input, "Renamed");
    await user.tab();

    await vi.advanceTimersByTimeAsync(11_000);

    await waitFor(() => expect(patches).toHaveLength(1));
    expect(patches[0]).toMatchObject({ name: "Renamed" });
    vi.useRealTimers();
  });
});
