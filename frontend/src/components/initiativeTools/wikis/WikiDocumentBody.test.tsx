import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { buildDocumentSummary } from "@/__tests__/factories";
import type { DocumentRead } from "@/api/generated/initiativeAPI.schemas";

import { isWideDocument, WikiDocumentBody } from "./WikiDocumentBody";

// Each kind's own renderer, stood in for by a line saying which it was and
// whether it was told to stay read-only.
vi.mock("@/components/documents/editor/editor", () => ({
  Editor: ({ readOnly }: { readOnly?: boolean }) => <p>prose {readOnly ? "read-only" : ""}</p>,
}));
vi.mock("@/components/documents/FileDocumentViewer", () => ({
  FileDocumentViewer: ({
    originalFilename,
    canEdit,
  }: {
    originalFilename?: string;
    canEdit?: boolean;
  }) => (
    <p>
      file {originalFilename} {canEdit ? "editable" : "read-only"}
    </p>
  ),
}));
vi.mock("@/components/documents/WhiteboardDocumentEditor", () => ({
  WhiteboardDocumentEditor: ({ readOnly }: { readOnly?: boolean }) => (
    <p>canvas {readOnly ? "read-only" : ""}</p>
  ),
}));
vi.mock("@/components/documents/SpreadsheetDocumentEditor", () => ({
  SpreadsheetDocumentEditor: ({ readOnly }: { readOnly?: boolean }) => (
    <p>grid {readOnly ? "read-only" : ""}</p>
  ),
}));
vi.mock("@/components/documents/SmartLinkDocumentViewer", () => ({
  SmartLinkDocumentViewer: () => <p>link</p>,
}));

const documentOf = (overrides: Partial<DocumentRead>) =>
  ({ ...buildDocumentSummary(), content: {}, ...overrides }) as DocumentRead;

describe("WikiDocumentBody", () => {
  it.each([
    [
      documentOf({
        document_type: "file",
        file_url: "/uploads/1/abc.pdf",
        original_filename: "proof.pdf",
      }),
      "file proof.pdf read-only",
    ],
    [documentOf({ document_type: "whiteboard" }), "canvas read-only"],
    [documentOf({ document_type: "spreadsheet" }), "grid read-only"],
    [documentOf({ document_type: "smart_link" }), "link"],
    [documentOf({ document_type: "native" }), "prose read-only"],
  ])("draws a document the way its own kind is drawn", async (document, expected) => {
    render(<WikiDocumentBody document={document} initiativeId={1} />);
    expect(await screen.findByText(expected)).toBeInTheDocument();
  });

  it("gives everything but prose the wide column", () => {
    expect(isWideDocument(documentOf({ document_type: "native" }))).toBe(false);
    expect(isWideDocument(documentOf({ document_type: "file" }))).toBe(true);
    expect(isWideDocument(undefined)).toBe(false);
  });
});
