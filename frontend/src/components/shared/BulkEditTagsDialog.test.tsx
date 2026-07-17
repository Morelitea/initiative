import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse } from "msw";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { guildHttp } from "@/__tests__/helpers/guildHttp";
import { server } from "@/__tests__/helpers/msw-server";
import { renderWithProviders } from "@/__tests__/helpers/render";
import type { TagBulkEditRequest } from "@/api/generated/initiativeAPI.schemas";

import { BulkEditTagsDialog } from "./BulkEditTagsDialog";

vi.mock("@/lib/chesterToast", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

const LABELS = {
  title: "Edit tags",
  descriptionAdd: "Add tags to items",
  descriptionRemove: "Remove tags from items",
  tabAdd: "Add",
  tabRemove: "Remove",
  addPlaceholder: "Pick tags",
  removePlaceholder: "Pick tags to remove",
  noTags: "No tags",
  tagsAdded: "Tags added",
  tagsRemoved: "Tags removed",
  applying: "Applying…",
  apply: "Apply",
  cancel: "Cancel",
  updateError: "Update failed",
};

const alpha = { id: 1, name: "alpha", color: "#6366F1" };
const beta = { id: 2, name: "beta", color: "#22C55E" };

describe("BulkEditTagsDialog", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    server.use(
      guildHttp.get("/tags/", () =>
        HttpResponse.json([
          { ...alpha, guild_id: 1, created_at: "", updated_at: "" },
          { ...beta, guild_id: 1, created_at: "", updated_at: "" },
        ])
      )
    );
  });

  it("adds tags with ONE bulk call carrying every selected item", async () => {
    const bodies: TagBulkEditRequest[] = [];
    server.use(
      guildHttp.post("/tags/bulk", async ({ request }) => {
        bodies.push((await request.json()) as TagBulkEditRequest);
        return HttpResponse.json({ updated_count: 2 });
      })
    );
    const onSuccess = vi.fn();
    const onInvalidate = vi.fn();

    renderWithProviders(
      <BulkEditTagsDialog
        open
        onOpenChange={vi.fn()}
        onSuccess={onSuccess}
        items={[
          { id: 11, tags: [] },
          { id: 12, tags: [beta] },
        ]}
        targetType="task"
        guildId={1}
        onInvalidate={onInvalidate}
        labels={LABELS}
      />
    );

    await userEvent.click(screen.getByRole("combobox"));
    await userEvent.click(await screen.findByText("alpha"));
    await userEvent.click(screen.getByRole("button", { name: LABELS.apply }));

    await waitFor(() => expect(onSuccess).toHaveBeenCalled());
    // The whole batch is one server-side call — no per-item fan-out, no
    // client-side merge of possibly-stale cached tags.
    expect(bodies).toEqual([
      {
        target_type: "task",
        target_ids: [11, 12],
        add_tag_ids: [alpha.id],
        remove_tag_ids: [],
      },
    ]);
    expect(onInvalidate).toHaveBeenCalledTimes(1);
  });

  it("removes tags via the remove tab with a remove-only payload", async () => {
    const bodies: TagBulkEditRequest[] = [];
    server.use(
      guildHttp.post("/tags/bulk", async ({ request }) => {
        bodies.push((await request.json()) as TagBulkEditRequest);
        return HttpResponse.json({ updated_count: 2 });
      })
    );

    renderWithProviders(
      <BulkEditTagsDialog
        open
        onOpenChange={vi.fn()}
        onSuccess={vi.fn()}
        items={[
          { id: 11, tags: [beta] },
          { id: 12, tags: [beta] },
        ]}
        targetType="document"
        guildId={1}
        onInvalidate={vi.fn()}
        labels={LABELS}
      />
    );

    await userEvent.click(screen.getByRole("tab", { name: LABELS.tabRemove }));
    await userEvent.click(screen.getByRole("combobox"));
    await userEvent.click(await screen.findByText("beta"));
    await userEvent.click(screen.getByRole("button", { name: LABELS.apply }));

    await waitFor(() =>
      expect(bodies).toEqual([
        {
          target_type: "document",
          target_ids: [11, 12],
          add_tag_ids: [],
          remove_tag_ids: [beta.id],
        },
      ])
    );
  });

  it("surfaces a failed bulk call and leaves the dialog open", async () => {
    server.use(
      guildHttp.post("/tags/bulk", () =>
        HttpResponse.json({ detail: "INVALID_TAG_IDS" }, { status: 400 })
      )
    );
    const onSuccess = vi.fn();
    const onOpenChange = vi.fn();

    renderWithProviders(
      <BulkEditTagsDialog
        open
        onOpenChange={onOpenChange}
        onSuccess={onSuccess}
        items={[{ id: 11, tags: [] }]}
        targetType="task"
        guildId={1}
        onInvalidate={vi.fn()}
        labels={LABELS}
      />
    );

    await userEvent.click(screen.getByRole("combobox"));
    await userEvent.click(await screen.findByText("alpha"));
    await userEvent.click(screen.getByRole("button", { name: LABELS.apply }));

    const { toast } = await import("@/lib/chesterToast");
    await waitFor(() => expect(toast.error).toHaveBeenCalled());
    expect(onSuccess).not.toHaveBeenCalled();
    expect(onOpenChange).not.toHaveBeenCalledWith(false);
  });
});
