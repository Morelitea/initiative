import { describe, expect, it, vi } from "vitest";
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";

import { renderWithProviders } from "@/__tests__/helpers/render";
import { server } from "@/__tests__/helpers/msw-server";
import { buildTrashItem, buildTrashListResponse } from "@/__tests__/factories/trash.factory";
import { buildUserGuildMember } from "@/__tests__/factories/user.factory";

import { TrashTable } from "./TrashTable";

// Hoist toast spy so we can assert on it without pulling the whole module.
vi.mock("@/lib/chesterToast", () => {
  const success = vi.fn();
  const error = vi.fn();
  return {
    toast: { success, error },
  };
});

const trashEndpoint = "/api/v1/trash/";
const restoreEndpoint = "/api/v1/trash/:type/:id/restore";
const purgeEndpoint = "/api/v1/trash/:type/:id/purge";

describe("TrashTable", () => {
  it("renders the empty state when the trash list is empty", async () => {
    server.use(http.get(trashEndpoint, () => HttpResponse.json(buildTrashListResponse([]))));

    renderWithProviders(<TrashTable scope="mine" showPurgeAction={false} />);

    expect(await screen.findByText(/Trash is empty\./i)).toBeInTheDocument();
  });

  it("renders one row per trashed item with type badge + name", async () => {
    server.use(
      http.get(trashEndpoint, () =>
        HttpResponse.json(
          buildTrashListResponse([
            buildTrashItem({ entity_type: "project", entity_id: 5, name: "Lost Mines" }),
            buildTrashItem({ entity_type: "task", entity_id: 7, name: "Find the cleric" }),
          ])
        )
      )
    );

    renderWithProviders(<TrashTable scope="guild" showPurgeAction />);

    expect(await screen.findByText("Lost Mines")).toBeInTheDocument();
    expect(screen.getByText("Find the cleric")).toBeInTheDocument();
    // entityType labels come from the trash namespace.
    expect(screen.getByText("Project")).toBeInTheDocument();
    expect(screen.getByText("Task")).toBeInTheDocument();
  });

  it("hides the Delete now column when showPurgeAction=false", async () => {
    server.use(
      http.get(trashEndpoint, () =>
        HttpResponse.json(
          buildTrashListResponse([buildTrashItem({ entity_type: "project", name: "Mine" })])
        )
      )
    );

    renderWithProviders(<TrashTable scope="mine" showPurgeAction={false} />);

    await screen.findByText("Mine");
    expect(screen.getByRole("button", { name: /Restore/i })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Delete now/i })).not.toBeInTheDocument();
  });

  it("clicking Restore POSTs to the restore endpoint and shows a success toast", async () => {
    const { toast } = await import("@/lib/chesterToast");
    const restoreCalls: string[] = [];

    server.use(
      http.get(trashEndpoint, () =>
        HttpResponse.json(
          buildTrashListResponse([
            buildTrashItem({ entity_type: "task", entity_id: 42, name: "Test task" }),
          ])
        )
      ),
      http.post(restoreEndpoint, ({ params }) => {
        restoreCalls.push(`${params.type}/${params.id}`);
        return HttpResponse.json({ restored: true });
      })
    );

    renderWithProviders(<TrashTable scope="mine" showPurgeAction={false} />);

    await screen.findByText("Test task");
    await userEvent.click(screen.getByRole("button", { name: /Restore/i }));

    await waitFor(() => expect(restoreCalls).toEqual(["task/42"]));
    await waitFor(() => expect(toast.success as ReturnType<typeof vi.fn>).toHaveBeenCalled());
  });

  it("opens the reassignment dialog when restore returns 200 + needs_reassignment", async () => {
    server.use(
      http.get(trashEndpoint, () =>
        HttpResponse.json(
          buildTrashListResponse([
            buildTrashItem({ entity_type: "task", entity_id: 42, name: "Owner-checked" }),
          ])
        )
      ),
      http.post(restoreEndpoint, () =>
        HttpResponse.json({
          needs_reassignment: true,
          valid_owner_ids: [11, 12],
          detail: "TRASH_NEEDS_REASSIGNMENT",
        })
      ),
      // ReassignOwnerDialog uses useUsers() to populate the picker.
      http.get("/api/v1/users/", () =>
        HttpResponse.json([
          buildUserGuildMember({ id: 11, full_name: "Alice" }),
          buildUserGuildMember({ id: 12, full_name: "Bob" }),
          buildUserGuildMember({ id: 99, full_name: "Outsider" }),
        ])
      )
    );

    renderWithProviders(<TrashTable scope="mine" showPurgeAction={false} />);

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
      http.get(trashEndpoint, () =>
        HttpResponse.json(
          buildTrashListResponse([
            buildTrashItem({ entity_type: "tag", entity_id: 9, name: "old-tag" }),
          ])
        )
      ),
      http.delete(purgeEndpoint, ({ params }) => {
        purgeCalls.push(`${params.type}/${params.id}`);
        return new HttpResponse(null, { status: 204 });
      })
    );

    renderWithProviders(<TrashTable scope="guild" showPurgeAction />);

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
