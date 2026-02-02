/**
 * Format bytes to a human-readable string.
 * @param bytes - Number of bytes
 * @param decimals - Number of decimal places (default: 1)
 */
export function formatBytes(bytes: number, decimals = 1): string {
  if (bytes === 0) return "0 Bytes";

  const k = 1024;
  const dm = decimals < 0 ? 0 : decimals;
  const sizes = ["Bytes", "KB", "MB", "GB", "TB"];

  const i = Math.floor(Math.log(bytes) / Math.log(k));

  return `${parseFloat((bytes / Math.pow(k, i)).toFixed(dm))} ${sizes[i]}`;
}

/**
 * Get the file extension from a filename or URL.
 * @param filename - Filename or URL path
 * @returns Extension without the dot (e.g., "pdf")
 */
export function getFileExtension(filename: string | null | undefined): string {
  if (!filename) return "";
  const lastDot = filename.lastIndexOf(".");
  if (lastDot === -1) return "";
  return filename.substring(lastDot + 1).toLowerCase();
}

/**
 * Get a display-friendly file type label from MIME type or extension.
 */
export function getFileTypeLabel(
  mimeType: string | null | undefined,
  filename: string | null | undefined
): string {
  // Try to get extension from filename first
  const ext = getFileExtension(filename);

  const extensionLabels: Record<string, string> = {
    pdf: "PDF",
    doc: "Word",
    docx: "Word",
    xls: "Excel",
    xlsx: "Excel",
    ppt: "PowerPoint",
    pptx: "PowerPoint",
    txt: "Text",
    html: "HTML",
    htm: "HTML",
  };

  if (ext && extensionLabels[ext]) {
    return extensionLabels[ext];
  }

  // Fall back to MIME type
  const mimeLabels: Record<string, string> = {
    "application/pdf": "PDF",
    "application/msword": "Word",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "Word",
    "application/vnd.ms-excel": "Excel",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "Excel",
    "application/vnd.ms-powerpoint": "PowerPoint",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": "PowerPoint",
    "text/plain": "Text",
    "text/html": "HTML",
  };

  if (mimeType && mimeLabels[mimeType]) {
    return mimeLabels[mimeType];
  }

  return "File";
}

/**
 * Get the icon name for a file type (for use with Lucide icons).
 */
export function getFileTypeIcon(
  mimeType: string | null | undefined,
  filename: string | null | undefined
): "file-text" | "file-spreadsheet" | "presentation" | "file-type" | "file" {
  const ext = getFileExtension(filename);

  if (ext === "pdf" || mimeType === "application/pdf") {
    return "file-text";
  }

  if (
    ext === "doc" ||
    ext === "docx" ||
    ext === "txt" ||
    mimeType === "application/msword" ||
    mimeType === "application/vnd.openxmlformats-officedocument.wordprocessingml.document" ||
    mimeType === "text/plain"
  ) {
    return "file-text";
  }

  if (
    ext === "xls" ||
    ext === "xlsx" ||
    mimeType === "application/vnd.ms-excel" ||
    mimeType === "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
  ) {
    return "file-spreadsheet";
  }

  if (
    ext === "ppt" ||
    ext === "pptx" ||
    mimeType === "application/vnd.ms-powerpoint" ||
    mimeType === "application/vnd.openxmlformats-officedocument.presentationml.presentation"
  ) {
    return "presentation";
  }

  if (ext === "html" || ext === "htm" || mimeType === "text/html") {
    return "file-type";
  }

  return "file";
}
