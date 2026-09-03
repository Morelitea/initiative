import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createEditor } from "lexical";
import { HttpResponse } from "msw";
import { describe, expect, it, vi } from "vitest";

import { guildHttp } from "@/__tests__/helpers/guildHttp";
import { server } from "@/__tests__/helpers/msw-server";
import { renderWithProviders } from "@/__tests__/helpers/render";
import { SmartChipInsertDialog } from "@/components/ui/editor/plugins/smart-chip-insert-dialog";

/**
 * What the picker offers, and what it says when it has nothing.
 *
 * It opens with no query typed, and the lookup matches words — so it cannot
 * answer "what could I point at", which is the question someone opening a
 * picker is actually asking. Recently edited work answers that; the states
 * below are what is left when even that is empty.
 */

const suggestion = {
  entity_type: "task",
  entity_id: 12,
  title: "Ship the release",
  initiative_id: 7,
  tool: "project",
  tool_id: 3,
};

const recent = { ...suggestion, entity_id: 5, title: "Draft the schedule" };

/** Nothing recent, nothing matching — the empty case for both lookups. */
const nothing = () => {
  server.use(
    guildHttp.get("/search/recent", () => HttpResponse.json([])),
    guildHttp.get("/search/suggest", () => HttpResponse.json([]))
  );
};

const open = (initiativeId: number | null = 7) =>
  renderWithProviders(
    <SmartChipInsertDialog
      chipKind={null}
      initiativeId={initiativeId}
      activeEditor={createEditor({
        onError: (error) => {
          throw error;
        },
      })}
      onClose={vi.fn()}
    />
  );

describe("choosing what a smart chip is about", () => {
  it("offers recently edited work before anything is typed", async () => {
    server.use(
      guildHttp.get("/search/recent", () => HttpResponse.json([recent])),
      guildHttp.get("/search/suggest", () => HttpResponse.json([]))
    );

    open();

    // The picker opens knowing something, rather than as a blank box.
    expect(await screen.findByText("Draft the schedule")).toBeInTheDocument();
    expect(screen.getByText(/Recently edited/)).toBeInTheDocument();
  });

  it("says so when there is nothing to point at yet", async () => {
    nothing();

    open();

    expect(await screen.findByText(/Nothing in this initiative to point at/)).toBeInTheDocument();
  });

  it("says nothing matched, and why the initiative is the limit", async () => {
    nothing();

    open();
    await userEvent.type(screen.getByRole("textbox"), "zzz");

    await waitFor(
      () => expect(screen.getByText(/Nothing in this initiative/)).toBeInTheDocument(),
      {
        timeout: 3000,
      }
    );
    expect(await screen.findByText(/Only this document.s initiative/)).toBeInTheDocument();
  });

  it("says a document outside an initiative has nothing to point at", async () => {
    open(null);

    expect(await screen.findByText(/isn.t in an initiative/)).toBeInTheDocument();
    // The initiative is not worth explaining to a document that has none.
    expect(screen.queryByText(/Only this document.s initiative/)).not.toBeInTheDocument();
  });

  it("lists what the lookup found", async () => {
    server.use(
      guildHttp.get("/search/recent", () => HttpResponse.json([recent])),
      guildHttp.get("/search/suggest", () => HttpResponse.json([suggestion]))
    );

    open();
    await userEvent.type(screen.getByRole("textbox"), "ship");

    await waitFor(() => expect(screen.getByText("Ship the release")).toBeInTheDocument(), {
      timeout: 3000,
    });
  });
});
