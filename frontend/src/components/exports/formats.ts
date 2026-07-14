import type { DocumentReadDocumentType } from "@/api/generated/initiativeAPI.schemas";
import { Tool } from "@/api/generated/initiativeAPI.schemas";
import type { ExportFormatOption } from "@/components/exports/ExportButton";

// Engine formats per document type — mirrors the backend adapter's rules.
export const DOCUMENT_TYPE_FORMATS: Record<DocumentReadDocumentType, ExportFormatOption[]> = {
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
  smart_link: [
    { format: "md", labelKey: "export.formatMarkdown" },
    { format: "json", labelKey: "export.formatJson" },
  ],
};

// Type-neutral labels for mixed-type selections, where a per-type label
// ("Lexical file (.lexical)") would misdescribe the other entries in the zip.
const GENERIC_FORMAT_LABELS: Record<string, string> = {
  pdf: "export.formatPdf",
  md: "export.formatMarkdown",
  docx: "export.formatDocx",
  json: "export.formatJson",
  csv: "export.formatCsv",
  xlsx: "export.formatXlsx",
  file: "export.formatOriginal",
};

/** Formats a document selection can export: the backend requires the format
 * to be valid for EVERY selected document's type, so offer the intersection.
 * A single-type selection keeps its type's own (more precise) labels; a
 * mixed selection gets generic ones. Empty when the types share nothing
 * (e.g. an upload + a text document). */
export function documentSelectionFormats(types: DocumentReadDocumentType[]): ExportFormatOption[] {
  const unique = [...new Set(types)];
  if (unique.length === 0) return [];
  if (unique.length === 1) return DOCUMENT_TYPE_FORMATS[unique[0]] ?? [];
  const formatSets = unique.map(
    (type) => new Set((DOCUMENT_TYPE_FORMATS[type] ?? []).map((f) => f.format))
  );
  const shared = [...formatSets[0]].filter((format) => formatSets.every((set) => set.has(format)));
  return shared.map((format) => ({
    format,
    labelKey: GENERIC_FORMAT_LABELS[format] ?? "export.formatJson",
  }));
}

// Per-tool export formats, keyed by the canonical Tool enum — each mirrors
// its backend adapter's format set. Documents are deliberately ABSENT: their
// formats depend on the selected documents' types (documentSelectionFormats
// above / DOCUMENT_TYPE_FORMATS). The registry drift test holds this table to
// TOOL_REGISTRY's bulkExport flags.
export const TOOL_EXPORT_FORMATS: Partial<Record<Tool, ExportFormatOption[]>> = {
  [Tool.project]: [
    // The importable JSON backup, then the task-table report formats.
    { format: "json", labelKey: "export.formatJson" },
    { format: "pdf", labelKey: "export.formatPdf" },
    { format: "csv", labelKey: "export.formatCsv" },
    { format: "xlsx", labelKey: "export.formatXlsx" },
  ],
  [Tool.queue]: [
    // Reports (Markdown renders a numbered turn order), then the envelope.
    { format: "pdf", labelKey: "export.formatPdf" },
    { format: "csv", labelKey: "export.formatCsv" },
    { format: "xlsx", labelKey: "export.formatXlsx" },
    { format: "md", labelKey: "export.formatMarkdown" },
    { format: "json", labelKey: "export.formatJson" },
  ],
  [Tool.counter_group]: [
    // Table reports, then the importable envelope.
    { format: "pdf", labelKey: "export.formatPdf" },
    { format: "csv", labelKey: "export.formatCsv" },
    { format: "xlsx", labelKey: "export.formatXlsx" },
    { format: "md", labelKey: "export.formatMd" },
    { format: "json", labelKey: "export.formatJson" },
  ],
  [Tool.calendar_event]: [
    // One combined calendar per export: standard iCalendar, or the
    // importable envelope.
    { format: "ics", labelKey: "export.formatIcs" },
    { format: "json", labelKey: "export.formatJson" },
  ],
};
