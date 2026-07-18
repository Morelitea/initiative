import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse, http } from "msw";
import { describe, expect, it, vi } from "vitest";

import { buildTrashItem, buildTrashListResponse } from "@/__tests__/factories/trash.factory";
import { guildHttp } from "@/__tests__/helpers/guildHttp";
import { server } from "@/__tests__/helpers/msw-server";
import { renderWithProviders } from "@/__tests__/helpers/render";

import { TrashTable } from "./TrashTable";

// Hoist toast spy so we can assert on it without pulling the whole module.
vi.mock("@/lib/chesterToast", () => {
  const success = vi.fn();
  const error = vi.fn();
  return {
    toast: { success, error },
  };
});

// variant="user" -> cross-guild GET /api/v1/me/trash (no guild segment).
const myTrashEndpoint = "/api/v1/me/trash";
// variant="guild" -> GET /api/v1/g/:guildId/trash/ (guild-admin view).
const guildTrashEndpoint = "/trash/";
// restore/purge stay guild-scoped, addressed by each item's guild_id.
const restoreEndpoint = "/trash/:type/:id/restore";
const purgeEndpoint = "/trash/:type/:id/purge";

describe("TrashTable", () => {
  it("renders the empty state when the trash list is empty", async () => {
    server.use(http.get(myTrashEndpoint, () => HttpResponse.json(buildTrashListResponse([]))));

    renderWithProviders(<TrashTable variant="user" showPurgeAction={false} />);

    expect(await screen.findByText(/Trash is empty\./i)).toBeInTheDocument();
  });

  it("renders one row per trashed item with type badge + name", async () => {
    server.use(
      guildHttp.get(guildTrashEndpoint, () =>
        HttpResponse.json(
          buildTrashListResponse([
            buildTrashItem({ entity_type: "project", entity_id: 5, name: "Lost Mines" }),
            buildTrashItem({ entity_type: "task", entity_id: 7, name: "Find the cleric" }),
          ])
        )
      )
    );

    renderWithProviders(<TrashTable variant="guild" showPurgeAction />);

    expect(await screen.findByText("Lost Mines")).toBeInTheDocument();
    expect(screen.getByText("Find the cleric")).toBeInTheDocument();
    // entityType labels come from the trash namespace.
    expect(screen.getByText("Project")).toBeInTheDocument();
    expect(screen.getByText("Task")).toBeInTheDocument();
  });

  it("hides the Delete now column when showPurgeAction=false", async () => {
    server.use(
      http.get(myTrashEndpoint, () =>
        HttpResponse.json(
          buildTrashListResponse([buildTrashItem({ entity_type: "project", name: "Mine" })])
        )
      )
    );

    renderWithProviders(<TrashTable variant="user" showPurgeAction={false} />);

    await screen.findByText("Mine");
    expect(screen.getByRole("button", { name: /Restore/i })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Delete now/i })).not.toBeInTheDocument();
  });

  it("clicking Restore POSTs to the restore endpoint and shows a success toast", async () => {
    const { toast } = await import("@/lib/chesterToast");
    const restoreCalls: string[] = [];

    server.use(
      http.get(myTrashEndpoint, () =>
        HttpResponse.json(
          buildTrashListResponse([
            buildTrashItem({ entity_type: "task", entity_id: 42, name: "Test task" }),
          ])
        )
      ),
      guildHttp.post(restoreEndpoint, ({ params }) => {
        restoreCalls.push(`${params.type}/${params.id}`);
        return HttpResponse.json({ restored: true });
      })
    );

    renderWithProviders(<TrashTable variant="user" showPurgeAction={false} />);

    await screen.findByText("Test task");
    await userEvent.click(screen.getByRole("button", { name: /Restore/i }));

    await waitFor(() => expect(restoreCalls).toEqual(["task/42"]));
    await waitFor(() => expect(toast.success as ReturnType<typeof vi.fn>).toHaveBeenCalled());
  });

  it("opens the reassignment dialog when restore returns 409 + needs_reassignment", async () => {
    server.use(
      http.get(myTrashEndpoint, () =>
        HttpResponse.json(
          buildTrashListResponse([
            buildTrashItem({ entity_type: "task", entity_id: 42, name: "Owner-checked" }),
          ])
        )
      ),
      // The 409 now carries the eligible owners inline (id + name), so the
      // dialog renders them directly without fetching the guild roster.
      guildHttp.post(restoreEndpoint, () =>
        HttpResponse.json(
          {
            needs_reassignment: true,
            valid_owner_ids: [11, 12],
            valid_owners: [
              { id: 11, full_name: "Alice" },
              { id: 12, full_name: "Bob" },
            ],
            detail: "TRASH_NEEDS_REASSIGNMENT",
          },
          { status: 409 }
        )
      )
    );

    renderWithProviders(<TrashTable variant="user" showPurgeAction={false} />);

    await screen.findByText("Owner-checked");
    await userEvent.click(screen.getByRole("button", { name: /Restore/i }));

    // The reassignment dialog should appear.
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText(/Pick a new owner/i)).toBeInTheDocument();
  });

  it("clicking Delete now opens a destructive confirmation and DELETEs on confirm", async () => {
    const { toast } = await import("@/lib/chesterToast");
    const purgeCalls: string[] = [];

    server.use(
      guildHttp.get(guildTrashEndpoint, () =>
        HttpResponse.json(
          buildTrashListResponse([
            buildTrashItem({ entity_type: "tag", entity_id: 9, name: "old-tag" }),
          ])
        )
      ),
      guildHttp.delete(purgeEndpoint, ({ params }) => {
        purgeCalls.push(`${params.type}/${params.id}`);
        return new HttpResponse(null, { status: 204 });
      })
    );

    renderWithProviders(<TrashTable variant="guild" showPurgeAction />);

    await screen.findByText("old-tag");
    await userEvent.click(screen.getByRole("button", { name: /Delete now/i }));

    // ConfirmDialog appears as an alertdialog with a destructive action.
    const confirm = await screen.findByRole("alertdialog");
    expect(within(confirm).getByText(/Delete permanently\?/i)).toBeInTheDocument();

    await userEvent.click(within(confirm).getByRole("button", { name: /Delete forever/i }));

    await waitFor(() => expect(purgeCalls).toEqual(["tag/9"]));
    await waitFor(() => expect(toast.success as ReturnType<typeof vi.fn>).toHaveBeenCalled());
  });
});
