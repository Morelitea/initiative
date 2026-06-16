import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { renderWithProviders } from "@/__tests__/helpers/render";
import type { DocumentFileVersionRead } from "@/api/generated/initiativeAPI.schemas";

// Avoid pulling in the real react-pdf (pdf.js worker) during tests.
vi.mock("react-pdf", () => ({
  Document: () => null,
  Page: () => null,
  pdfjs: { GlobalWorkerOptions: {}, version: "test" },
}));

// Fixed, predictable download URLs so we can assert which version is rendered.
vi.mock("@/lib/uploadUrl", () => ({
  resolveDocumentDownloadUrl: (id: number, inline?: boolean) =>
    `/dl/${id}${inline ? "?inline=1" : ""}`,
  resolveDocumentVersionDownloadUrl: (id: number, vid: number, inline?: boolean) =>
    `/dl/${id}/v/${vid}${inline ? "?inline=1" : ""}`,
}));

const uploadMutate = vi.fn();
const deleteMutate = vi.fn();
let mockVersions: DocumentFileVersionRead[] = [];

vi.mock("@/hooks/useDocuments", () => ({
  useDocumentVersions: () => ({ data: mockVersions }),
  useUploadDocumentVersion: () => ({ mutate: uploadMutate, isPending: false }),
  useDeleteDocumentVersion: () => ({ mutate: deleteMutate, isPending: false }),
}));

// Import after mocks are registered.
import { FileDocumentViewer } from "./FileDocumentViewer";

const buildVersion = (overrides: Partial<DocumentFileVersionRead>): DocumentFileVersionRead => ({
  id: 1,
  version_number: 1,
  file_content_type: "application/pdf",
  file_size: 100,
  original_filename: "doc.pdf",
  uploaded_by_id: 1,
  created_at: "2026-05-28T00:00:00Z",
  is_current: false,
  ...overrides,
});

const renderViewer = (props: Partial<Parameters<typeof FileDocumentViewer>[0]> = {}) =>
  renderWithProviders(
    <FileDocumentViewer
      documentId={5}
      guildId={7}
      fileUrl="/uploads/doc.pdf"
      contentType="application/pdf"
      originalFilename="doc.pdf"
      fileSize={100}
      {...props}
    />
  );

describe("FileDocumentViewer version controls", () => {
  beforeEach(() => {
    uploadMutate.mockClear();
    deleteMutate.mockClear();
    mockVersions = [
      buildVersion({ id: 2, version_number: 2, is_current: true }),
      buildVersion({ id: 1, version_number: 1, is_current: false }),
    ];
  });

  it("hides upload + delete for a read-only viewer", async () => {
    renderViewer({ canEdit: false, isOwner: false });
    await userEvent.click(screen.getByRole("button", { name: /version history/i }));
    expect(screen.queryByText(/upload new version/i)).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /delete version/i })).not.toBeInTheDocument();
  });

  it("shows the upload action for a writer", async () => {
    renderViewer({ canEdit: true, isOwner: false });
    await userEvent.click(screen.getByRole("button", { name: /version history/i }));
    expect(screen.getByText(/upload new version/i)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /delete version/i })).not.toBeInTheDocument();
  });

  it("lets the owner delete a non-last version", async () => {
    renderViewer({ canEdit: true, isOwner: true });
    await userEvent.click(screen.getByRole("button", { name: /version history/i }));
    const deleteButtons = screen.getAllByRole("button", { name: /delete version/i });
    expect(deleteButtons.length).toBe(2);
    expect(deleteButtons[0]).toBeEnabled();
  });

  it("disables delete when only one version exists", async () => {
    mockVersions = [buildVersion({ id: 2, version_number: 1, is_current: true })];
    renderViewer({ canEdit: true, isOwner: true });
    await userEvent.click(screen.getByRole("button", { name: /version history/i }));
    expect(screen.getByRole("button", { name: /delete version/i })).toBeDisabled();
  });

  it("switches the viewer to an older version and shows the notice", async () => {
    renderViewer({ canEdit: true, isOwner: true });
    await userEvent.click(screen.getByRole("button", { name: /version history/i }));
    await userEvent.click(screen.getByRole("button", { name: /version 1/i }));
    await waitFor(() => expect(screen.getByText(/viewing an older version/i)).toBeInTheDocument());
  });
});
