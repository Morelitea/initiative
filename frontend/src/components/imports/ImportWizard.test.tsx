import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse } from "msw";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { guildHttp } from "@/__tests__/helpers/guildHttp";
import { server } from "@/__tests__/helpers/msw-server";
import { renderWithProviders } from "@/__tests__/helpers/render";

import { ImportWizard } from "./ImportWizard";

vi.mock("@/lib/chesterToast", () => ({
  toast: { success: vi.fn(), error: vi.fn(), warning: vi.fn() },
}));

// The wizard's first step reads the manifest from the local file; stub the
// peek so the test doesn't need a real zip.
vi.mock("@/lib/backupPeek", () => ({
  BackupPeekError: class extends Error {
    code: string;
    constructor(code: string) {
      super(code);
      this.code = code;
    }
  },
  peekBackupManifest: vi.fn(),
}));

import { peekBackupManifest } from "@/lib/backupPeek";

const MANIFEST = {
  type: "guild-backup",
  guild: { name: "Old Guild" },
  app_version: "0.56.0",
  exported_at: "2026-07-15T00:00:00Z",
  initiatives: [{ id: 1, name: "Lore", tools: {} }],
  entries: [{ tool: "queue" }, { tool: "document" }],
  assets: [{ size_bytes: 2_500_000 }],
};

const STAGED_JOB = {
  id: 55,
  guild_id: 1,
  created_by_id: 1,
  source: "backup",
  params: {},
  status: "staged",
  plan: {
    source_guild_name: "Old Guild",
    initiatives: [
      {
        source_id: 1,
        name: "Lore",
        proposed_name: "Lore (imported)",
        entry_counts: { queue: 1, document: 1 },
      },
    ],
    asset_count: 1,
    asset_bytes: 2_500_000,
    skipped: [],
    unknown_types: [],
  },
  result: null,
  error: null,
  expires_at: null,
  created_at: new Date().toISOString(),
  updated_at: new Date().toISOString(),
};

function pickFile() {
  const input = document.querySelector<HTMLInputElement>('input[type="file"]');
  if (!input) throw new Error("no file input");
  const file = new File([new Uint8Array([1, 2, 3])], "backup.zip", {
    type: "application/zip",
  });
  Object.defineProperty(input, "files", { value: [file], configurable: true });
  input.dispatchEvent(new Event("change", { bubbles: true }));
}

describe("ImportWizard", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    localStorage.clear();
    (peekBackupManifest as ReturnType<typeof vi.fn>).mockResolvedValue(MANIFEST);
  });

  it("peeks locally, uploads, shows the server plan, confirms, and reports", async () => {
    let uploaded = false;
    let confirmed = false;
    let pollCount = 0;
    server.use(
      guildHttp.post("/imports/backup", () => {
        uploaded = true;
        return HttpResponse.json(STAGED_JOB, { status: 201 });
      }),
      guildHttp.post("/imports/jobs/:jobId/confirm", () => {
        confirmed = true;
        return HttpResponse.json({ ...STAGED_JOB, status: "queued" });
      }),
      guildHttp.get("/imports/jobs/:jobId", () => {
        pollCount += 1;
        // First poll running, then done.
        if (pollCount < 2) {
          return HttpResponse.json({ ...STAGED_JOB, status: "running" });
        }
        return HttpResponse.json({
          ...STAGED_JOB,
          status: "done",
          result: {
            initiatives: [{ source_id: 1, initiative_id: 9, name: "Lore (imported)" }],
            per_tool: { queue: { created: 1, failed: 0, skipped: 0 } },
            entries: [],
            assets_restored: 1,
            assets_deduped: 0,
            unmatched_emails: [],
          },
        });
      })
    );

    renderWithProviders(<ImportWizard open onOpenChange={() => {}} />);

    pickFile();

    // Local peek preview — nothing uploaded yet.
    expect(await screen.findByText(/Backup of Old Guild/i)).toBeInTheDocument();
    expect(screen.getByText(/2\.4 MB/)).toBeInTheDocument();
    expect(uploaded).toBe(false);

    await userEvent.click(screen.getByRole("button", { name: /upload backup/i }));

    // The server's authoritative plan.
    expect(await screen.findByText(/Lore \(imported\)/i)).toBeInTheDocument();
    expect(uploaded).toBe(true);

    await userEvent.click(screen.getByRole("button", { name: /start import/i }));
    await waitFor(() => expect(confirmed).toBe(true));

    // Polls to done → report.
    expect(await screen.findByText(/import finished/i, {}, { timeout: 4000 })).toBeInTheDocument();
    expect(screen.getByText(/1 initiative created/i)).toBeInTheDocument();
  });

  it("rejects a non-backup file at the peek step without uploading", async () => {
    const { BackupPeekError } = await import("@/lib/backupPeek");
    (peekBackupManifest as ReturnType<typeof vi.fn>).mockRejectedValue(
      new BackupPeekError("not_backup")
    );
    let uploaded = false;
    server.use(
      guildHttp.post("/imports/backup", () => {
        uploaded = true;
        return HttpResponse.json(STAGED_JOB, { status: 201 });
      })
    );

    renderWithProviders(<ImportWizard open onOpenChange={() => {}} />);
    pickFile();

    expect(await screen.findByText(/isn't a valid Initiative backup/i)).toBeInTheDocument();
    expect(uploaded).toBe(false);
    expect(screen.queryByRole("button", { name: /upload backup/i })).not.toBeInTheDocument();
  });
});
