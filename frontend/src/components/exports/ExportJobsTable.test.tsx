import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse } from "msw";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { guildHttp } from "@/__tests__/helpers/guildHttp";
import { server } from "@/__tests__/helpers/msw-server";
import { renderWithProviders } from "@/__tests__/helpers/render";

import { ExportJobsTable } from "./ExportJobsTable";

vi.mock("@/lib/csv", () => ({ downloadBlob: vi.fn() }));
vi.mock("@/lib/chesterToast", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

import { downloadBlob } from "@/lib/csv";

const now = new Date().toISOString();
const job = (overrides: Record<string, unknown>) => ({
  id: 1,
  guild_id: 1,
  created_by_id: 1,
  source: "guild",
  template_id: "data-table",
  format: "zip",
  params: {},
  status: "done",
  error: null,
  expires_at: new Date(Date.now() + 86_400_000).toISOString(),
  created_at: now,
  updated_at: now,
  ...overrides,
});

describe("ExportJobsTable", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("lists jobs and offers download only for finished ones", async () => {
    server.use(
      guildHttp.get("/exports/", () =>
        HttpResponse.json([
          job({ id: 1, source: "guild", status: "done" }),
          job({ id: 2, source: "initiative", status: "failed", expires_at: null }),
          job({ id: 3, source: "project", status: "expired", expires_at: null }),
        ])
      )
    );

    renderWithProviders(<ExportJobsTable />);

    expect(await screen.findByText("Guild")).toBeInTheDocument();
    expect(screen.getByText("Ready")).toBeInTheDocument();
    expect(screen.getByText("Failed")).toBeInTheDocument();
    expect(screen.getByText("Expired")).toBeInTheDocument();
    // One download button: the done row only.
    expect(screen.getAllByRole("button", { name: /download/i })).toHaveLength(1);
  });

  it("re-downloads a finished artifact via the job download route", async () => {
    let hit = false;
    server.use(
      guildHttp.get("/exports/", () => HttpResponse.json([job({ id: 9 })])),
      guildHttp.get("/exports/:jobId/download", () => {
        hit = true;
        return HttpResponse.text("PK-zip", {
          headers: {
            "Content-Type": "application/zip",
            "Content-Disposition": 'attachment; filename="guild-backup.zip"',
          },
        });
      })
    );

    renderWithProviders(<ExportJobsTable />);
    await userEvent.click(await screen.findByRole("button", { name: /download/i }));

    await waitFor(() => expect(hit).toBe(true));
    await waitFor(() =>
      expect(downloadBlob).toHaveBeenCalledWith(expect.anything(), "guild-backup.zip")
    );
  });

  it("shows the empty state when there are no jobs", async () => {
    server.use(guildHttp.get("/exports/", () => HttpResponse.json([])));
    renderWithProviders(<ExportJobsTable />);
    expect(await screen.findByText(/no exports yet/i)).toBeInTheDocument();
  });
});
