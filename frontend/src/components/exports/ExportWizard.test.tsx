import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse } from "msw";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { guildHttp } from "@/__tests__/helpers/guildHttp";
import { server } from "@/__tests__/helpers/msw-server";
import { renderWithProviders } from "@/__tests__/helpers/render";

import { ExportWizard } from "./ExportWizard";

vi.mock("@/lib/csv", () => ({ downloadBlob: vi.fn() }));
vi.mock("@/lib/chesterToast", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

import { downloadBlob } from "@/lib/csv";

const ESTIMATE = {
  tools: {
    project: { count: 3, disabled: false },
    document: { count: 5, disabled: false },
    queue: { count: 0, disabled: true },
    counter_group: { count: 2, disabled: false },
    calendar_event: { count: 4, disabled: false },
  },
  uploads_count: 1,
  uploads_bytes: 2_500_000,
  uploads_approximate: true,
  estimated_rows: 40,
  max_rows: 50_000,
  max_upload_bytes: 268_435_456,
};

function stubEstimate(estimate = ESTIMATE) {
  server.use(guildHttp.get("/exports/estimate", () => HttpResponse.json(estimate)));
}

function stubJobLifecycle(capture: (url: URL) => void) {
  server.use(
    guildHttp.get("/exports/guild", ({ request }) => {
      capture(new URL(request.url));
      return HttpResponse.json({ id: 77, status: "queued" }, { status: 202 });
    }),
    guildHttp.get("/exports/initiative", ({ request }) => {
      capture(new URL(request.url));
      return HttpResponse.json({ id: 77, status: "queued" }, { status: 202 });
    }),
    guildHttp.get("/exports/:jobId", ({ params }) => {
      // Fall through for the literal sibling routes (/exports/estimate,
      // /exports/guild, /exports/initiative) — only numeric ids are jobs.
      if (Number.isNaN(Number(params.jobId))) {
        return undefined;
      }
      return HttpResponse.json({
        id: 77,
        guild_id: 1,
        created_by_id: 1,
        source: "guild",
        template_id: "data-table",
        format: "zip",
        params: {},
        status: "done",
        error: null,
        expires_at: null,
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
      });
    }),
    guildHttp.get("/exports/:jobId/download", () =>
      HttpResponse.text("PK-zip", {
        headers: {
          "Content-Type": "application/zip",
          "Content-Disposition": 'attachment; filename="guild-backup.zip"',
        },
      })
    )
  );
}

describe("ExportWizard", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    localStorage.clear();
  });

  it("walks the backup flow and submits the backup selector", async () => {
    stubEstimate();
    let sent: URL | null = null;
    stubJobLifecycle((url) => {
      sent = url;
    });

    renderWithProviders(<ExportWizard scope="guild" open onOpenChange={() => {}} />);

    await userEvent.click(screen.getByRole("button", { name: /importable backup/i }));

    // Estimate renders per-tool counts; a disabled tool shows "Not enabled"
    // with its switch off and locked.
    await screen.findByText("3 items");
    expect(screen.getByText(/not enabled/i)).toBeInTheDocument();
    expect(screen.getByRole("switch", { name: /queues/i })).toBeDisabled();
    // Uploads footprint from the estimate, human-formatted.
    expect(screen.getByText(/2\.4 MB/)).toBeInTheDocument();

    // Exclude counters, keep uploads on.
    await userEvent.click(screen.getByRole("switch", { name: /counters/i }));
    await userEvent.click(screen.getByRole("button", { name: /next/i }));

    await userEvent.click(screen.getByRole("button", { name: /start export/i }));

    await waitFor(() => expect(sent).not.toBeNull());
    const params = sent!.searchParams;
    expect(params.get("mode")).toBe("backup");
    expect(params.get("include_uploads")).toBe("true");
    expect(JSON.parse(params.get("include")!)).toMatchObject({
      project: true,
      document: true,
      counter_group: false,
    });
    expect(params.get("formats")).toBeNull();

    // The 202 job polls to done and auto-downloads.
    await waitFor(() => expect(downloadBlob).toHaveBeenCalled(), { timeout: 4000 });
    expect(await screen.findByText(/export ready/i)).toBeInTheDocument();
  });

  it("submits per-tool report formats including the document per-type map", async () => {
    let sent: URL | null = null;
    stubJobLifecycle((url) => {
      sent = url;
    });

    renderWithProviders(
      <ExportWizard scope="initiative" initiativeId={5} open onOpenChange={() => {}} />
    );

    await userEvent.click(screen.getByRole("button", { name: /report à la carte/i }));

    // Change the project format from its default (pdf) to CSV. Several tools
    // offer CSV — target the project group's radio by its id.
    const projectCsv = screen
      .getAllByRole("radio", { name: /csv/i })
      .find((radio) => radio.id === "project-csv");
    expect(projectCsv).toBeDefined();
    await userEvent.click(projectCsv!);
    await userEvent.click(screen.getByRole("button", { name: /next/i }));
    await userEvent.click(screen.getByRole("button", { name: /start export/i }));

    await waitFor(() => expect(sent).not.toBeNull());
    const params = sent!.searchParams;
    expect(params.get("initiative_id")).toBe("5");
    expect(params.get("mode")).toBe("report");
    const formats = JSON.parse(params.get("formats")!);
    expect(formats.project).toBe("csv");
    expect(formats.document).toEqual({ native: "pdf", spreadsheet: "xlsx" });
    expect(formats.calendar_event).toBe("ics");
    expect(params.get("include_uploads")).toBeNull();
  });

  it("blocks the backup step when the estimate exceeds a ceiling", async () => {
    stubEstimate({
      ...ESTIMATE,
      uploads_bytes: 300_000_000,
      max_upload_bytes: 268_435_456,
    });

    renderWithProviders(<ExportWizard scope="guild" open onOpenChange={() => {}} />);
    await userEvent.click(screen.getByRole("button", { name: /importable backup/i }));

    expect(await screen.findByText(/exceed the 256 MB limit/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /next/i })).toBeDisabled();

    // Excluding uploads clears the block (the re-fetched estimate reflects
    // include_uploads=false only server-side; client-side the toggle alone
    // stops counting bytes against the cap).
    await userEvent.click(screen.getByRole("switch", { name: /include uploaded files/i }));
    await waitFor(() => expect(screen.getByRole("button", { name: /next/i })).not.toBeDisabled());
  });
});
