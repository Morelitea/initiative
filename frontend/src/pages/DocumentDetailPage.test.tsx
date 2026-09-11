import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse } from "msw";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { buildDocumentSummary } from "@/__tests__/factories";
import { guildHttp } from "@/__tests__/helpers/guildHttp";
import { server } from "@/__tests__/helpers/msw-server";
import { renderPage } from "@/__tests__/helpers/render";

const collaborating = { value: false };
const sendContent = vi.fn();

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
    sendContent,
  }),
}));

// Stands in for Lexical, exposing the one thing these tests drive: a body edit,
// reported back the way the real editor reports one.
vi.mock("@/components/documents/editor/editor", () => ({
  Editor: ({ onSerializedChange }: { onSerializedChange: (state: unknown) => void }) => (
    <button
      type="button"
      onClick={() => onSerializedChange({ root: { children: [{ type: "edited" }] } })}
    >
      edit the body
    </button>
  ),
}));

const seed = buildDocumentSummary({ id: 7, name: "Original", initiative_id: 1 });

const patches: Record<string, unknown>[] = [];
/** What the server holds — a PATCH keeps what it was given, as the real one does. */
let stored: Record<string, unknown> = { ...seed };

beforeEach(() => {
  patches.length = 0;
  stored = { ...seed };
  sendContent.mockClear();
  collaborating.value = false;
  server.use(
    guildHttp.get("/documents/:documentId", () => HttpResponse.json(stored)),
    guildHttp.patch("/documents/:documentId", async ({ request }) => {
      const body = (await request.json()) as Record<string, unknown>;
      patches.push(body);
      stored = { ...stored, ...body };
      return HttpResponse.json(stored);
    }),
    guildHttp.post("/recents/", () => HttpResponse.json({})),
    guildHttp.get("/relationships/", () => HttpResponse.json([])),
    guildHttp.get("/properties/definitions", () => HttpResponse.json([]))
  );
});

const { DocumentDetailPage } = await import("./DocumentDetailPage");

// Restored here rather than at the end of each test so a failed assertion
// cannot leave fake timers behind for the next one.
afterEach(() => {
  vi.useRealTimers();
});

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
  });

  it("keeps saving the body while the name field is held", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    renderDoc();

    const input = await screen.findByDisplayValue("Original");
    await user.click(await screen.findByRole("button", { name: "edit the body" }));
    await user.clear(input);
    await user.type(input, "Renamed");

    await vi.advanceTimersByTimeAsync(6000);

    // The body went; the half-typed name stayed behind with its Save button.
    await waitFor(() => expect(patches).toHaveLength(1));
    expect(patches[0]).toHaveProperty("content");
    expect(patches[0]).not.toHaveProperty("name");
    expect(screen.getByRole("button", { name: "Save" })).not.toBeDisabled();
  });

  it("keeps the room's content sync running while the name field is held", async () => {
    collaborating.value = true;
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    renderDoc();

    const input = await screen.findByDisplayValue("Original");
    await user.click(await screen.findByRole("button", { name: "edit the body" }));
    await user.clear(input);
    await user.type(input, "Renamed");

    await vi.advanceTimersByTimeAsync(11_000);

    await waitFor(() => expect(sendContent).toHaveBeenCalled());
    expect(patches).toHaveLength(1);
    expect(patches[0]).not.toHaveProperty("name");
  });

  it("does not PATCH on a loop while collaborating with nothing edited", async () => {
    collaborating.value = true;
    vi.useFakeTimers({ shouldAdvanceTime: true });
    renderDoc();
    await screen.findByDisplayValue("Original");

    await vi.advanceTimersByTimeAsync(45_000);

    expect(patches).toEqual([]);
    expect(sendContent).not.toHaveBeenCalled();
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
  });
});
