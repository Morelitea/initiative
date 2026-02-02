import { useState, useRef, useEffect } from "react";
import { Document, Page, pdfjs } from "react-pdf";
import {
  Download,
  ExternalLink,
  FileSpreadsheet,
  FileText,
  Loader2,
  Presentation,
  ZoomIn,
  ZoomOut,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import { resolveUploadUrl } from "@/lib/uploadUrl";
import { formatBytes, getFileTypeLabel, getFileExtension } from "@/lib/fileUtils";

import "react-pdf/dist/Page/AnnotationLayer.css";
import "react-pdf/dist/Page/TextLayer.css";

// Configure PDF.js worker from CDN (most reliable for Vite)
pdfjs.GlobalWorkerOptions.workerSrc = `//unpkg.com/pdfjs-dist@${pdfjs.version}/build/pdf.worker.min.mjs`;

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

  // PDF viewer state
  const [numPages, setNumPages] = useState<number | null>(null);
  const [scale, setScale] = useState(1.0);
  const [pdfError, setPdfError] = useState<string | null>(null);
  const [baseWidth, setBaseWidth] = useState<number | null>(null);
  const toolbarRef = useRef<HTMLDivElement>(null);

  // Measure toolbar width once on mount for PDF sizing
  useEffect(() => {
    const measureWidth = () => {
      if (toolbarRef.current) {
        setBaseWidth(toolbarRef.current.clientWidth);
      }
    };

    // Measure after a short delay to ensure layout is complete
    const timeoutId = setTimeout(measureWidth, 50);
    return () => clearTimeout(timeoutId);
  }, []);

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

  const onDocumentLoadSuccess = ({ numPages }: { numPages: number }) => {
    setNumPages(numPages);
    setPdfError(null);
  };

  const onDocumentLoadError = (error: Error) => {
    console.error("PDF load error:", error);
    setPdfError("Failed to load PDF. Try downloading the file instead.");
  };

  const zoomIn = () => setScale((prev) => Math.min(2.5, prev + 0.25));
  const zoomOut = () => setScale((prev) => Math.max(0.5, prev - 0.25));

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

      <div
        className="bg-card w-full min-w-0 overflow-hidden rounded-lg border"
        style={baseWidth ? { maxWidth: baseWidth } : undefined}
      >
        {isPdf ? (
          <div className="flex w-full flex-col overflow-hidden">
            {/* PDF Controls */}
            <div
              ref={toolbarRef}
              className="bg-muted/50 flex flex-wrap items-center justify-between gap-2 border-b px-4 py-2"
            >
              <span className="text-muted-foreground text-sm">
                {numPages ? `${numPages} page${numPages > 1 ? "s" : ""}` : "Loading..."}
              </span>
              <div className="flex items-center gap-2">
                <Button variant="outline" size="sm" onClick={zoomOut} disabled={scale <= 0.5}>
                  <ZoomOut className="h-4 w-4" />
                </Button>
                <span className="w-16 text-center text-sm">{Math.round(scale * 100)}%</span>
                <Button variant="outline" size="sm" onClick={zoomIn} disabled={scale >= 2.5}>
                  <ZoomIn className="h-4 w-4" />
                </Button>
              </div>
            </div>

            {/* PDF Viewer */}
            <div
              className="min-w-0 overflow-auto bg-neutral-100 p-4 dark:bg-neutral-900"
              style={{ height: "70vh", minHeight: 500, maxWidth: "100%" }}
            >
              {pdfError ? (
                <div className="flex h-full flex-col items-center justify-center text-center">
                  <FileText className="text-muted-foreground mb-4 h-16 w-16" />
                  <p className="text-muted-foreground mb-4">{pdfError}</p>
                  <Button onClick={handleDownload}>
                    <Download className="mr-2 h-4 w-4" />
                    Download PDF
                  </Button>
                </div>
              ) : baseWidth ? (
                <Document
                  file={resolvedUrl}
                  onLoadSuccess={onDocumentLoadSuccess}
                  onLoadError={onDocumentLoadError}
                  loading={
                    <div className="flex h-full items-center justify-center">
                      <Loader2 className="text-muted-foreground h-8 w-8 animate-spin" />
                    </div>
                  }
                >
                  <div className="flex flex-col items-center gap-4">
                    {Array.from({ length: numPages || 0 }, (_, index) => (
                      <Page
                        key={index + 1}
                        pageNumber={index + 1}
                        width={(baseWidth - 32) * scale}
                        loading={
                          <div className="flex items-center justify-center p-8">
                            <Loader2 className="text-muted-foreground h-6 w-6 animate-spin" />
                          </div>
                        }
                      />
                    ))}
                  </div>
                </Document>
              ) : (
                <div className="flex h-full items-center justify-center">
                  <Loader2 className="text-muted-foreground h-8 w-8 animate-spin" />
                </div>
              )}
            </div>
          </div>
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
            sandbox=""
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
