import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse } from "msw";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { buildDocumentSummary } from "@/__tests__/factories";
import { communityHttp } from "@/__tests__/helpers/communityHttp";
import { server } from "@/__tests__/helpers/msw-server";
import { renderWithProviders } from "@/__tests__/helpers/render";

import { DocumentsBulkBar } from "./DocumentsBulkBar";

vi.mock("@/lib/csv", () => ({ downloadBlob: vi.fn() }));
vi.mock("@/lib/chesterToast", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

import { downloadBlob } from "@/lib/csv";

const noop = () => {};

const barProps = {
  canEditSelectedDocuments: true,
  canDuplicateSelectedDocuments: true,
  canDeleteSelectedDocuments: true,
  onBulkEditTags: noop,
  onBulkEditAccess: noop,
  onBulkDuplicate: noop,
  isBulkDuplicating: false,
  onBulkDelete: noop,
  isBulkDeleting: false,
};

describe("DocumentsBulkBar export", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    localStorage.clear();
  });

  it("sends the selected ids and downloads the zip", async () => {
    let sent: string[] = [];
    server.use(
      communityHttp.get("/exports/document", ({ request }) => {
        sent = new URL(request.url).searchParams.getAll("ids");
        return new HttpResponse("PK-zip-bytes", {
          status: 200,
          headers: {
            "Content-Type": "application/zip",
            "Content-Disposition": 'attachment; filename="document-2026-07-14.zip"',
          },
        });
      })
    );
    const docs = [
      buildDocumentSummary({ id: 11, document_type: "native" }),
      buildDocumentSummary({ id: 12, document_type: "native" }),
    ];
    renderWithProviders(<DocumentsBulkBar {...barProps} selectedDocuments={docs} />);

    await userEvent.click(screen.getByRole("button", { name: /export/i }));
    await userEvent.click(await screen.findByRole("button", { name: /json/i }));
    await userEvent.click(screen.getByRole("button", { name: /start export/i }));

    await waitFor(() => expect(downloadBlob).toHaveBeenCalledTimes(1));
    expect(sent).toEqual(["11", "12"]);
    // Server names the bundle; the client fallback stem never fires.
    expect(vi.mocked(downloadBlob).mock.calls[0][1]).toBe("document-2026-07-14.zip");
  });

  it("offers only the intersection for a mixed selection", async () => {
    const docs = [
      buildDocumentSummary({ id: 1, document_type: "native" }),
      buildDocumentSummary({ id: 2, document_type: "spreadsheet" }),
    ];
    renderWithProviders(<DocumentsBulkBar {...barProps} selectedDocuments={docs} />);

    // json is the only shared format, so the wizard asks nothing and names it.
    await userEvent.click(screen.getByRole("button", { name: /export/i }));
    expect(await screen.findByRole("button", { name: /start export/i })).toBeInTheDocument();
    expect(screen.getByText(/json/i)).toBeInTheDocument();
    expect(screen.queryByText(/pdf|csv/i)).not.toBeInTheDocument();
  });

  it("disables export when the selected types share no format", () => {
    const docs = [
      buildDocumentSummary({ id: 1, document_type: "native" }),
      buildDocumentSummary({ id: 2, document_type: "file" }),
    ];
    renderWithProviders(<DocumentsBulkBar {...barProps} selectedDocuments={docs} />);

    const exportButton = screen.getByRole("button", { name: /export/i });
    expect(exportButton).toBeDisabled();
  });
});
