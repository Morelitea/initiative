import { Download, ExternalLink, FileSpreadsheet, FileText, Presentation } from "lucide-react";

import { Button } from "@/components/ui/button";
import { resolveUploadUrl } from "@/lib/uploadUrl";
import { formatBytes, getFileTypeLabel, getFileExtension } from "@/lib/fileUtils";

interface FileDocumentViewerProps {
  fileUrl: string;
  contentType?: string | null;
  originalFilename?: string | null;
  fileSize?: number | null;
}

export const FileDocumentViewer = ({
  fileUrl,
  contentType,
  originalFilename,
  fileSize,
}: FileDocumentViewerProps) => {
  const resolvedUrl = resolveUploadUrl(fileUrl);
  const fileTypeLabel = getFileTypeLabel(contentType, originalFilename);
  const extension = getFileExtension(originalFilename || fileUrl);

  // Determine file type for rendering strategy
  const isPdf = extension === "pdf" || contentType === "application/pdf";
  const isText = extension === "txt" || contentType === "text/plain";
  const isHtml = extension === "html" || extension === "htm" || contentType === "text/html";

  // Office documents can't be rendered in-browser without external services
  const isWord =
    ["doc", "docx"].includes(extension) ||
    contentType === "application/msword" ||
    contentType === "application/vnd.openxmlformats-officedocument.wordprocessingml.document";
  const isExcel =
    ["xls", "xlsx"].includes(extension) ||
    contentType === "application/vnd.ms-excel" ||
    contentType === "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet";
  const isPowerPoint =
    ["ppt", "pptx"].includes(extension) ||
    contentType === "application/vnd.ms-powerpoint" ||
    contentType === "application/vnd.openxmlformats-officedocument.presentationml.presentation";
  const isOffice = isWord || isExcel || isPowerPoint;

  const handleDownload = () => {
    if (!resolvedUrl) return;

    const link = document.createElement("a");
    link.href = resolvedUrl;
    link.download = originalFilename || "document";
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  };

  const handleOpenInNewTab = () => {
    if (!resolvedUrl) return;
    window.open(resolvedUrl, "_blank", "noopener,noreferrer");
  };

  if (!resolvedUrl) {
    return (
      <div className="text-muted-foreground flex items-center justify-center rounded-lg border p-8">
        <p>Unable to load document</p>
      </div>
    );
  }

  // Get the appropriate icon for Office documents
  const OfficeIcon = isExcel ? FileSpreadsheet : isPowerPoint ? Presentation : FileText;
  const iconColor = isExcel ? "text-green-600" : isPowerPoint ? "text-orange-500" : "text-blue-600";

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="text-muted-foreground text-sm">
          <span className="font-medium">{fileTypeLabel}</span>
          {fileSize && <span className="ml-2">({formatBytes(fileSize)})</span>}
          {originalFilename && (
            <span className="ml-2 inline-block max-w-[200px] truncate align-bottom">
              {originalFilename}
            </span>
          )}
        </div>
        <div className="flex gap-2">
          <Button variant="outline" size="sm" onClick={handleOpenInNewTab}>
            <ExternalLink className="mr-2 h-4 w-4" />
            Open in new tab
          </Button>
          <Button variant="outline" size="sm" onClick={handleDownload}>
            <Download className="mr-2 h-4 w-4" />
            Download
          </Button>
        </div>
      </div>

      <div className="bg-card overflow-hidden rounded-lg border">
        {isPdf ? (
          // Use native browser PDF viewer via embed/object
          <object
            data={resolvedUrl}
            type="application/pdf"
            className="w-full"
            style={{ height: "70vh", minHeight: 500 }}
          >
            <embed src={resolvedUrl} type="application/pdf" className="h-full w-full" />
            <p className="text-muted-foreground p-4 text-center">
              Your browser does not support embedded PDFs.{" "}
              <a
                href={resolvedUrl}
                target="_blank"
                rel="noopener noreferrer"
                className="text-primary underline"
              >
                Open PDF in new tab
              </a>
            </p>
          </object>
        ) : isText ? (
          // Use iframe for text files
          <iframe
            src={resolvedUrl}
            className="bg-muted w-full"
            style={{ height: "70vh", minHeight: 500 }}
            title={originalFilename || "Text document"}
          />
        ) : isHtml ? (
          // Use sandboxed iframe for HTML files
          <iframe
            src={resolvedUrl}
            className="w-full"
            style={{ height: "70vh", minHeight: 500 }}
            title={originalFilename || "HTML document"}
            sandbox="allow-same-origin"
          />
        ) : isOffice ? (
          // Office documents - show preview card with download options
          <div
            className="bg-muted/50 flex flex-col items-center justify-center"
            style={{ height: "70vh", minHeight: 500 }}
          >
            <OfficeIcon className={`h-24 w-24 ${iconColor} mb-6`} />
            <h3 className="mb-2 text-xl font-semibold">{originalFilename || "Document"}</h3>
            <p className="text-muted-foreground mb-6 max-w-md text-center">
              {fileTypeLabel} files cannot be previewed in the browser.
              <br />
              Download the file to view it in{" "}
              {isWord ? "Microsoft Word" : isExcel ? "Microsoft Excel" : "Microsoft PowerPoint"} or
              a compatible application.
            </p>
            <div className="flex gap-3">
              <Button onClick={handleDownload}>
                <Download className="mr-2 h-4 w-4" />
                Download {fileTypeLabel}
              </Button>
              <Button variant="outline" onClick={handleOpenInNewTab}>
                <ExternalLink className="mr-2 h-4 w-4" />
                Open in new tab
              </Button>
            </div>
          </div>
        ) : (
          // Unknown file type - show generic download prompt
          <div
            className="bg-muted/50 flex flex-col items-center justify-center"
            style={{ height: "70vh", minHeight: 500 }}
          >
            <FileText className="text-muted-foreground mb-6 h-24 w-24" />
            <h3 className="mb-2 text-xl font-semibold">{originalFilename || "Document"}</h3>
            <p className="text-muted-foreground mb-6">
              This file type cannot be previewed in the browser.
            </p>
            <Button onClick={handleDownload}>
              <Download className="mr-2 h-4 w-4" />
              Download file
            </Button>
          </div>
        )}
      </div>
    </div>
  );
};
