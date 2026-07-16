import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse } from "msw";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { guildHttp } from "@/__tests__/helpers/guildHttp";
import { server } from "@/__tests__/helpers/msw-server";
import { renderWithProviders } from "@/__tests__/helpers/render";

import { DataJobsTable } from "./DataJobsTable";

vi.mock("@/lib/chesterToast", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));
vi.mock("@/lib/exportDownload", () => ({
  downloadExportArtifact: vi.fn(),
}));

import { downloadExportArtifact } from "@/lib/exportDownload";

const now = new Date();
const iso = (offsetMs: number) => new Date(now.getTime() + offsetMs).toISOString();

const exportJob = (o: Record<string, unknown>) => ({
  id: 1,
  guild_id: 1,
  created_by_id: 1,
  source: "guild",
  template_id: "data-table",
  format: "zip",
  params: {},
  status: "done",
  error: null,
  expires_at: iso(86_400_000),
  created_at: iso(-1000),
  updated_at: iso(-1000),
  ...o,
});
const importJob = (o: Record<string, unknown>) => ({
  id: 1,
  guild_id: 1,
  created_by_id: 1,
  source: "backup",
  params: {},
  plan: null,
  result: null,
  status: "queued",
  error: null,
  expires_at: null,
  created_at: iso(-500),
  updated_at: iso(-500),
  ...o,
});

describe("DataJobsTable", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("interleaves both directions with direction-specific actions", async () => {
    server.use(
      guildHttp.get("/exports/", () => HttpResponse.json([exportJob({ id: 10, status: "done" })])),
      guildHttp.get("/imports/jobs", () =>
        HttpResponse.json([
          importJob({ id: 20, status: "queued", created_at: iso(0) }),
          importJob({ id: 21, status: "done", created_at: iso(-2000) }),
        ])
      )
    );

    renderWithProviders(<DataJobsTable />);

    // Newest first: the queued import (created now) leads.
    const rows = await screen.findAllByRole("row");
    // header + 3 data rows
    expect(rows).toHaveLength(4);
    // Direction badges (the column HEADER also says "Export"; badges are the
    // two Import rows plus one Export row).
    expect(screen.getAllByText("Import")).toHaveLength(2);

    // Export done → Download; import queued → Cancel; import done → View report.
    expect(screen.getByRole("button", { name: /download/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /cancel/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /view report/i })).toBeInTheDocument();
  });

  it("re-downloads a finished export via the download helper", async () => {
    server.use(
      guildHttp.get("/exports/", () => HttpResponse.json([exportJob({ id: 10, status: "done" })])),
      guildHttp.get("/imports/jobs", () => HttpResponse.json([]))
    );
    renderWithProviders(<DataJobsTable />);
    await userEvent.click(await screen.findByRole("button", { name: /download/i }));
    await waitFor(() => expect(downloadExportArtifact).toHaveBeenCalled());
  });

  it("cancels a staged/queued import", async () => {
    let cancelled = false;
    server.use(
      guildHttp.get("/exports/", () => HttpResponse.json([])),
      guildHttp.get("/imports/jobs", () =>
        HttpResponse.json([importJob({ id: 20, status: "staged" })])
      ),
      guildHttp.delete("/imports/jobs/:jobId", () => {
        cancelled = true;
        return HttpResponse.json({ ...importJob({ id: 20 }), status: "cancelled" });
      })
    );
    renderWithProviders(<DataJobsTable />);
    await userEvent.click(await screen.findByRole("button", { name: /cancel/i }));
    await waitFor(() => expect(cancelled).toBe(true));
  });

  it("clamps a stale done export whose artifact has expired", async () => {
    server.use(
      guildHttp.get("/exports/", () =>
        HttpResponse.json([exportJob({ id: 10, status: "done", expires_at: iso(-60_000) })])
      ),
      guildHttp.get("/imports/jobs", () => HttpResponse.json([]))
    );
    renderWithProviders(<DataJobsTable />);
    expect(await screen.findByText("Expired")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /download/i })).not.toBeInTheDocument();
  });
});
