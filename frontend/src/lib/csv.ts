export const escapeCsvValue = (value: unknown): string => {
  const str = value == null ? "" : String(value);
  return /[",\n\r]/.test(str) ? `"${str.replace(/"/g, '""')}"` : str;
};

export const downloadCsv = (
  headers: readonly string[],
  rows: readonly (readonly unknown[])[],
  filename: string
): void => {
  const body = rows.map((row) => row.map(escapeCsvValue).join(",")).join("\n");
  const csv = `${headers.join(",")}\n${body}\n`;
  // Prepend UTF-8 BOM so Excel auto-detects the encoding instead of falling back
  // to the system code page (often Windows-1252) and garbling accented chars.
  const blob = new Blob(["\uFEFF", csv], { type: "text/csv;charset=utf-8;" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  // Firefox ignores .click() on detached anchors, so attach before clicking.
  document.body.appendChild(anchor);
  try {
    anchor.click();
  } finally {
    anchor.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
};
