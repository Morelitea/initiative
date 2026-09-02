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
 * What the picker says when it has nothing to offer.
 *
 * It opens with no query, and the lookup answers nothing for an empty one — so
 * every one of these states used to render as a blank box under a search field,
 * which reads as a broken dialog rather than as an answer.
 */

const suggestion = {
  entity_type: "task",
  entity_id: 12,
  title: "Ship the release",
  initiative_id: 7,
  tool: "project",
  tool_id: 3,
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
  it("asks for a search rather than showing an empty box", async () => {
    server.use(guildHttp.get("/search/suggest", () => HttpResponse.json([])));

    open();

    expect(await screen.findByText(/Type to find something/)).toBeInTheDocument();
  });

  it("says nothing matched, and why the initiative is the limit", async () => {
    server.use(guildHttp.get("/search/suggest", () => HttpResponse.json([])));

    open();
    await userEvent.type(screen.getByRole("textbox"), "zzz");

    await waitFor(
      () => expect(screen.getByText(/Nothing in this initiative/)).toBeInTheDocument(),
      {
        timeout: 3000,
      }
    );
    expect(screen.getByText(/Only this document.s initiative/)).toBeInTheDocument();
  });

  it("says a document outside an initiative has nothing to point at", async () => {
    open(null);

    expect(await screen.findByText(/isn.t in an initiative/)).toBeInTheDocument();
  });

  it("lists what the lookup found", async () => {
    server.use(guildHttp.get("/search/suggest", () => HttpResponse.json([suggestion])));

    open();
    await userEvent.type(screen.getByRole("textbox"), "ship");

    await waitFor(() => expect(screen.getByText("Ship the release")).toBeInTheDocument(), {
      timeout: 3000,
    });
  });
});
