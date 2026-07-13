import { useRef } from "react";
import { useTranslation } from "react-i18next";

import type { DocumentReadDocumentType } from "@/api/generated/initiativeAPI.schemas";
import type { WhiteboardScene } from "@/components/documents/WhiteboardDocumentEditor";
import { ExportButton, type ExportFormatOption } from "@/components/exports/ExportButton";
import { toast } from "@/lib/chesterToast";
import { downloadBlob } from "@/lib/csv";
import { exportFilenameStem } from "@/lib/exportDownload";

interface DocumentExportMenuProps {
  documentId: number;
  documentType: DocumentReadDocumentType;
  title: string;
  /** Whiteboards only: the live scene, for client-side PNG/SVG rendering —
   * only Excalidraw's own renderer draws scenes faithfully, so pixels are
   * produced in the browser while the engine handles the importable JSON. */
  whiteboardScene?: WhiteboardScene;
}

// Engine formats per document type — mirrors the backend adapter's rules.
const TYPE_FORMATS: Record<DocumentReadDocumentType, ExportFormatOption[]> = {
  native: [
    { format: "pdf", labelKey: "export.formatPdf" },
    { format: "md", labelKey: "export.formatMarkdown" },
    { format: "docx", labelKey: "export.formatDocx" },
    // The lossless one: round-trips through the editor toolbar's import.
    { format: "json", labelKey: "export.formatLexical" },
  ],
  whiteboard: [{ format: "json", labelKey: "export.formatExcalidraw" }],
  spreadsheet: [
    { format: "csv", labelKey: "export.formatCsv" },
    { format: "xlsx", labelKey: "export.formatXlsx" },
    { format: "json", labelKey: "export.formatJson" },
  ],
  file: [{ format: "file", labelKey: "export.formatOriginal" }],
  smart_link: [{ format: "md", labelKey: "export.formatMarkdown" }],
};

export function DocumentExportMenu({
  documentId,
  documentType,
  title,
  whiteboardScene,
}: DocumentExportMenuProps) {
  const { t } = useTranslation("tasks");
  const stem = exportFilenameStem(title, "document");
  // Engine entries are debounced by ExportButton's busy state; the
  // client-side renders need their own in-flight guard.
  const sceneExporting = useRef(false);

  const exportScene = async (kind: "png" | "svg") => {
    if (!whiteboardScene || sceneExporting.current) {
      return;
    }
    sceneExporting.current = true;
    try {
      // Lazy: the excalidraw bundle is heavy and the menu renders on every
      // document page.
      const { exportToBlob, exportToSvg } = await import("@excalidraw/excalidraw");
      if (kind === "png") {
        const blob = await exportToBlob({
          elements: whiteboardScene.elements,
          appState: whiteboardScene.appState,
          files: whiteboardScene.files,
          mimeType: "image/png",
        });
        downloadBlob(blob, `${stem}.png`);
      } else {
        const svg = await exportToSvg({
          elements: whiteboardScene.elements,
          appState: whiteboardScene.appState,
          files: whiteboardScene.files,
        });
        const blob = new Blob([svg.outerHTML], { type: "image/svg+xml" });
        downloadBlob(blob, `${stem}.svg`);
      }
      toast.success(t("export.success"));
    } catch {
      toast.error(t("export.error"));
    } finally {
      sceneExporting.current = false;
    }
  };

  const extraActions =
    documentType === "whiteboard" && whiteboardScene
      ? [
          { labelKey: "export.formatPng", onSelect: () => void exportScene("png") },
          { labelKey: "export.formatSvg", onSelect: () => void exportScene("svg") },
        ]
      : undefined;

  return (
    <ExportButton
      endpoint="/exports/document"
      params={{ document_id: documentId }}
      formats={TYPE_FORMATS[documentType] ?? []}
      filenameStem={stem}
      extraActions={extraActions}
    />
  );
}
