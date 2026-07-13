import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse } from "msw";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { guildHttp } from "@/__tests__/helpers/guildHttp";
import { server } from "@/__tests__/helpers/msw-server";
import { renderWithProviders } from "@/__tests__/helpers/render";

import { DocumentExportMenu } from "./DocumentExportMenu";

vi.mock("@/lib/csv", () => ({ downloadBlob: vi.fn() }));
vi.mock("@/lib/chesterToast", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));
vi.mock("@excalidraw/excalidraw", () => ({
  exportToBlob: vi.fn(async () => new Blob(["png"], { type: "image/png" })),
  exportToSvg: vi.fn(async () => {
    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    return svg;
  }),
}));

import { exportToBlob } from "@excalidraw/excalidraw";

import { downloadBlob } from "@/lib/csv";

describe("DocumentExportMenu", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    localStorage.clear();
  });

  it("offers spreadsheet formats and sends the engine request", async () => {
    let sent: { format: string | null; document_id: string | null } | null = null;
    server.use(
      guildHttp.get("/exports/document", ({ request }) => {
        const url = new URL(request.url);
        sent = {
          format: url.searchParams.get("format"),
          document_id: url.searchParams.get("document_id"),
        };
        return new HttpResponse("a,b", {
          status: 200,
          headers: { "Content-Type": "text/csv" },
        });
      })
    );
    renderWithProviders(
      <DocumentExportMenu documentId={9} documentType="spreadsheet" title="Budget" />
    );

    await userEvent.click(screen.getByRole("button", { name: /export/i }));
    await userEvent.click(await screen.findByRole("menuitem", { name: /csv/i }));

    await waitFor(() => expect(downloadBlob).toHaveBeenCalledTimes(1));
    expect(sent).toEqual({ format: "csv", document_id: "9" });
    expect(String(vi.mocked(downloadBlob).mock.calls[0][1])).toMatch(/^budget-.*\.csv$/);
  });

  it("names the download from the server's Content-Disposition (.lexical)", async () => {
    server.use(
      guildHttp.get(
        "/exports/document",
        () =>
          new HttpResponse("{}", {
            status: 200,
            headers: {
              "Content-Type": "application/json",
              "Content-Disposition": 'attachment; filename="notes-2026-07-13.lexical"',
            },
          })
      )
    );
    renderWithProviders(<DocumentExportMenu documentId={5} documentType="native" title="Notes" />);

    await userEvent.click(screen.getByRole("button", { name: /export/i }));

    await waitFor(() => expect(downloadBlob).toHaveBeenCalledTimes(1));
    // The server name wins over the client's {stem}.{format} fallback —
    // .lexical is what the editor's import picker accepts, not .json.
    expect(vi.mocked(downloadBlob).mock.calls[0][1]).toBe("notes-2026-07-13.lexical");
  });

  it("renders whiteboard PNG client-side without touching the engine", async () => {
    const engineHit = vi.fn();
    server.use(
      guildHttp.get("/exports/document", () => {
        engineHit();
        return HttpResponse.json({});
      })
    );
    renderWithProviders(
      <DocumentExportMenu
        documentId={4}
        documentType="whiteboard"
        title="Board"
        whiteboardScene={{ elements: [], appState: {}, files: {} }}
      />
    );

    await userEvent.click(screen.getByRole("button", { name: /export/i }));
    await userEvent.click(await screen.findByRole("menuitem", { name: /png/i }));

    await waitFor(() => expect(downloadBlob).toHaveBeenCalledTimes(1));
    expect(exportToBlob).toHaveBeenCalledTimes(1);
    expect(engineHit).not.toHaveBeenCalled();
    expect(String(vi.mocked(downloadBlob).mock.calls[0][1])).toMatch(/^board-.*\.png$/);
  });

  it("renders a plain button for single-format types (file passthrough)", async () => {
    server.use(
      guildHttp.get(
        "/exports/document",
        () =>
          new HttpResponse("bytes", {
            status: 200,
            headers: { "Content-Type": "application/pdf" },
          })
      )
    );
    renderWithProviders(<DocumentExportMenu documentId={2} documentType="file" title="Upload" />);

    // Single engine format, no extras: the button itself exports.
    await userEvent.click(screen.getByRole("button", { name: /export/i }));
    expect(screen.queryByRole("menuitem")).not.toBeInTheDocument();
    await waitFor(() => expect(downloadBlob).toHaveBeenCalledTimes(1));
  });
});
