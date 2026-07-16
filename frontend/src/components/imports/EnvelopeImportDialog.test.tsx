import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse } from "msw";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { buildInitiative } from "@/__tests__/factories";
import { guildHttp } from "@/__tests__/helpers/guildHttp";
import { server } from "@/__tests__/helpers/msw-server";
import { renderWithProviders } from "@/__tests__/helpers/render";
import { Tool } from "@/api/generated/initiativeAPI.schemas";

import { EnvelopeImportDialog } from "./EnvelopeImportDialog";

vi.mock("@/lib/chesterToast", () => ({
  toast: { success: vi.fn(), error: vi.fn(), warning: vi.fn() },
}));

const initiative = buildInitiative({ id: 7, name: "Target" });

vi.mock("@/hooks/useInitiatives", () => ({
  useInitiatives: () => ({ data: [initiative] }),
}));
vi.mock("@/hooks/useInitiativeAccess", () => ({
  useInitiativeAccess: () => ({
    filterVisible: (list: unknown[]) => list,
    permissionsFor: () => ({
      [Tool.queue]: { create: true },
      [Tool.document]: { create: true },
    }),
  }),
}));

import { toast } from "@/lib/chesterToast";

function selectFile(contents: object) {
  const input = screen.getByLabelText(/export file/i) as HTMLInputElement;
  const file = new File([JSON.stringify(contents)], "export.json", {
    type: "application/json",
  });
  // jsdom doesn't run File.text() from a change event; stub it on the file.
  Object.defineProperty(file, "text", { value: () => Promise.resolve(JSON.stringify(contents)) });
  Object.defineProperty(input, "files", { value: [file], configurable: true });
  input.dispatchEvent(new Event("change", { bubbles: true }));
}

describe("EnvelopeImportDialog", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("imports a matching envelope into the chosen initiative", async () => {
    let sent: Record<string, unknown> | null = null;
    server.use(
      guildHttp.post("/imports/envelope", async ({ request }) => {
        sent = (await request.json()) as Record<string, unknown>;
        return HttpResponse.json(
          { result: { entity_title: "Restored Queue", created: {}, unmatched_emails: [] } },
          { status: 201 }
        );
      })
    );

    renderWithProviders(<EnvelopeImportDialog tool={Tool.queue} open onOpenChange={() => {}} />);

    selectFile({ type: "initiative-queue", name: "Restored Queue", schema_version: 1 });
    // A single creatable initiative is auto-selected; the Import button enables.
    const importBtn = await screen.findByRole("button", { name: /^import$/i });
    await waitFor(() => expect(importBtn).not.toBeDisabled());
    await userEvent.click(importBtn);

    await waitFor(() => expect(sent).not.toBeNull());
    expect(sent).toMatchObject({
      initiative_id: 7,
      envelope: { type: "initiative-queue" },
    });
    await waitFor(() =>
      expect(toast.success).toHaveBeenCalledWith(expect.stringContaining("Restored Queue"))
    );
  });

  it("rejects a file whose type belongs to a different tool", async () => {
    renderWithProviders(<EnvelopeImportDialog tool={Tool.queue} open onOpenChange={() => {}} />);
    selectFile({ type: "initiative-document", title: "Notes", schema_version: 1 });
    expect(await screen.findByText(/import it from that tool's page/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^import$/i })).toBeDisabled();
  });

  it("rejects a file that isn't an Initiative export", async () => {
    renderWithProviders(<EnvelopeImportDialog tool={Tool.queue} open onOpenChange={() => {}} />);
    selectFile({ hello: "world" });
    expect(await screen.findByText(/isn't a recognized Initiative export/i)).toBeInTheDocument();
  });
});
