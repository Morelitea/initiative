import { ImagePlus } from "lucide-react";
import {
  type DragEvent,
  forwardRef,
  type ReactNode,
  useImperativeHandle,
  useRef,
  useState,
} from "react";
import { useTranslation } from "react-i18next";

import { ACCEPT_ATTRIBUTE } from "@/lib/galleries";
import { cn } from "@/lib/utils";

export interface GalleryDropzoneHandle {
  /** Open the file dialog — for a button somewhere else on the page. */
  open: () => void;
}

interface GalleryDropzoneProps {
  /** Whether dropping does anything. A reader without write access sees the
   *  wall and no overlay. */
  enabled: boolean;
  onFiles: (files: File[]) => void;
  className?: string;
  children: ReactNode;
}

/**
 * The wall as a place to drop pictures.
 *
 * Wraps the whole gallery rather than offering a box at the top: forty files
 * dragged from a folder land wherever the cursor is, and the cursor is over
 * the pictures. A counter rather than a boolean tracks the drag, because
 * `dragenter`/`dragleave` fire for every child the cursor crosses and a
 * boolean would flicker the overlay off over each tile.
 *
 * The same component owns the file input, so "Add pictures" and a drop go
 * through one `onFiles`.
 */
export const GalleryDropzone = forwardRef<GalleryDropzoneHandle, GalleryDropzoneProps>(
  ({ enabled, onFiles, className, children }, ref) => {
    const { t } = useTranslation("galleries");
    const inputRef = useRef<HTMLInputElement | null>(null);
    const depth = useRef(0);
    const [dragging, setDragging] = useState(false);

    useImperativeHandle(ref, () => ({ open: () => inputRef.current?.click() }), []);

    // A drag that began inside the wall — a picture, a link, a selection —
    // is not files arriving from outside, whatever the browser puts in its
    // types list. Only a drag that started elsewhere is one to take.
    const internalDrag = useRef(false);
    const hasFiles = (event: DragEvent) =>
      !internalDrag.current && Array.from(event.dataTransfer.types).includes("Files");

    const onDragEnter = (event: DragEvent) => {
      if (!enabled || !hasFiles(event)) return;
      event.preventDefault();
      depth.current += 1;
      setDragging(true);
    };
    const onDragOver = (event: DragEvent) => {
      if (!enabled || !hasFiles(event)) return;
      event.preventDefault();
      event.dataTransfer.dropEffect = "copy";
    };
    const onDragLeave = (event: DragEvent) => {
      if (!enabled || !hasFiles(event)) return;
      depth.current = Math.max(0, depth.current - 1);
      if (depth.current === 0) setDragging(false);
    };
    const onDrop = (event: DragEvent) => {
      if (!enabled || !hasFiles(event)) return;
      event.preventDefault();
      depth.current = 0;
      setDragging(false);
      const files = Array.from(event.dataTransfer.files);
      if (files.length > 0) onFiles(files);
    };

    return (
      <div
        className={cn("relative", className)}
        onDragStart={() => {
          internalDrag.current = true;
        }}
        onDragEnd={() => {
          internalDrag.current = false;
        }}
        onDragEnter={onDragEnter}
        onDragOver={onDragOver}
        onDragLeave={onDragLeave}
        onDrop={onDrop}
      >
        {children}
        {enabled && (
          <input
            ref={inputRef}
            type="file"
            accept={ACCEPT_ATTRIBUTE}
            multiple
            className="sr-only"
            tabIndex={-1}
            aria-hidden
            onChange={(event) => {
              const files = Array.from(event.target.files ?? []);
              // The same file twice in a row is a new choice, not a repeat.
              event.target.value = "";
              if (files.length > 0) onFiles(files);
            }}
          />
        )}
        {dragging && (
          <div className="pointer-events-none absolute inset-0 z-20 flex items-center justify-center rounded-xl border-2 border-primary border-dashed bg-background/80 backdrop-blur-sm">
            <div className="flex flex-col items-center gap-2 text-primary">
              <ImagePlus className="size-10" aria-hidden />
              <p className="font-medium">{t("dropzone.prompt")}</p>
            </div>
          </div>
        )}
      </div>
    );
  }
);
GalleryDropzone.displayName = "GalleryDropzone";
