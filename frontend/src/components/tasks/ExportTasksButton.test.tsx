import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse } from "msw";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { guildHttp } from "@/__tests__/helpers/guildHttp";
import { server } from "@/__tests__/helpers/msw-server";
import { renderWithProviders } from "@/__tests__/helpers/render";
import type { ExportJobRead } from "@/api/generated/initiativeAPI.schemas";

import { ExportTasksButton } from "./ExportTasksButton";

vi.mock("@/lib/csv", () => ({ downloadBlob: vi.fn() }));
vi.mock("@/lib/chesterToast", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

import { toast } from "@/lib/chesterToast";
import { downloadBlob } from "@/lib/csv";
import { getItem, setItem } from "@/lib/storage";

const PDF = new Uint8Array([0x25, 0x50, 0x44, 0x46]); // "%PDF"

const buildJob = (overrides: Partial<ExportJobRead> = {}): ExportJobRead => ({
  id: 7,
  guild_id: 1,
  created_by_id: 1,
  source: "tasks",
  template_id: "task-table",
  format: "pdf",
  params: {},
  status: "queued",
  error: null,
  expires_at: null,
  created_at: "2026-07-12T00:00:00Z",
  updated_at: "2026-07-12T00:00:00Z",
  ...overrides,
});

const pdfResponse = () =>
  new HttpResponse(PDF, { status: 200, headers: { "Content-Type": "application/pdf" } });

describe("ExportTasksButton", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    localStorage.clear();
  });

  it("downloads the PDF directly on an inline (200) export", async () => {
    server.use(guildHttp.get("/exports/tasks", () => pdfResponse()));
    renderWithProviders(<ExportTasksButton params={{ conditions: [] }} />);

    await userEvent.click(screen.getByRole("button", { name: /export pdf/i }));

    await waitFor(() => expect(downloadBlob).toHaveBeenCalledTimes(1));
    expect(vi.mocked(downloadBlob).mock.calls[0][1]).toBe("tasks.pdf");
    expect(toast.success).toHaveBeenCalled();
    expect(toast.error).not.toHaveBeenCalled();
  });

  it("polls a queued (202) job and downloads when it finishes", async () => {
    server.use(
      guildHttp.get("/exports/tasks", () => HttpResponse.json(buildJob(), { status: 202 })),
      guildHttp.get("/exports/:jobId", () => HttpResponse.json(buildJob({ status: "done" }))),
      guildHttp.get("/exports/:jobId/download", () => pdfResponse())
    );
    renderWithProviders(<ExportTasksButton params={{ conditions: [] }} />);

    await userEvent.click(screen.getByRole("button", { name: /export pdf/i }));

    await waitFor(() => expect(downloadBlob).toHaveBeenCalledTimes(1));
    expect(vi.mocked(downloadBlob).mock.calls[0][1]).toBe("tasks-7.pdf");
  });

  it("surfaces a failed job as an error toast, without downloading", async () => {
    server.use(
      guildHttp.get("/exports/tasks", () => HttpResponse.json(buildJob(), { status: 202 })),
      guildHttp.get("/exports/:jobId", () =>
        HttpResponse.json(buildJob({ status: "failed", error: "EXPORT_RENDER_FAILED" }))
      )
    );
    renderWithProviders(<ExportTasksButton params={{ conditions: [] }} />);

    await userEvent.click(screen.getByRole("button", { name: /export pdf/i }));

    await waitFor(() => expect(toast.error).toHaveBeenCalledTimes(1));
    expect(downloadBlob).not.toHaveBeenCalled();
  });

  it("sends the given selector on the wire and honors a label override", async () => {
    let sentConditions: unknown = null;
    server.use(
      guildHttp.get("/exports/tasks", ({ request }) => {
        const raw = new URL(request.url).searchParams.get("conditions");
        sentConditions = raw ? JSON.parse(raw) : null;
        return pdfResponse();
      })
    );
    renderWithProviders(
      <ExportTasksButton
        params={{ conditions: [{ field: "id", op: "in_", value: [3, 5] }] }}
        label="Export Selected"
      />
    );

    await userEvent.click(screen.getByRole("button", { name: "Export Selected" }));

    await waitFor(() => expect(downloadBlob).toHaveBeenCalledTimes(1));
    expect(sentConditions).toEqual([{ field: "id", op: "in_", value: [3, 5] }]);
  });

  it("resumes a pending job from storage on mount and downloads it", async () => {
    setItem("exports:pending:1", "9");
    server.use(
      guildHttp.get("/exports/:jobId", () =>
        HttpResponse.json(buildJob({ id: 9, status: "done" }))
      ),
      guildHttp.get("/exports/:jobId/download", () => pdfResponse())
    );
    renderWithProviders(<ExportTasksButton params={{ conditions: [] }} />);

    await waitFor(() => expect(downloadBlob).toHaveBeenCalledTimes(1));
    expect(vi.mocked(downloadBlob).mock.calls[0][1]).toBe("tasks-9.pdf");
    // The pending marker is consumed, so a remount won't re-download.
    expect(getItem("exports:pending:1")).toBeNull();
  });

  it("shows a localized error for a rejected export (too large)", async () => {
    server.use(
      guildHttp.get("/exports/tasks", () =>
        HttpResponse.json({ detail: "EXPORT_TOO_LARGE" }, { status: 400 })
      )
    );
    renderWithProviders(<ExportTasksButton params={{ conditions: [] }} />);

    await userEvent.click(screen.getByRole("button", { name: /export pdf/i }));

    await waitFor(() => expect(toast.error).toHaveBeenCalledTimes(1));
    expect(downloadBlob).not.toHaveBeenCalled();
  });
});
