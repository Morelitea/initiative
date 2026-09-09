import { ChevronLeft, ChevronRight, X } from "lucide-react";
import { type ReactNode, useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/dialog";
import { cn } from "@/lib/utils";

export interface LightboxItem {
  /** Stable identity — what a caller keys on when the list changes under it. */
  id: number | string;
  src: string;
  alt: string;
  /** Drawn under the picture: a title, a byline, a date. */
  caption?: ReactNode;
}

interface LightboxProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  items: LightboxItem[];
  index: number;
  onIndexChange: (index: number) => void;
  /** Controls drawn in the top bar beside the close button — details, a
   *  download link, whatever the caller has for this picture. */
  actions?: ReactNode;
  /** Called as the reader nears the end of `items`, so a caller feeding it
   *  from a paged list can fetch the next page before they arrive. */
  onNearEnd?: () => void;
}

/** How far a finger has to travel, as a share of the width, before a drag is
 *  a swipe rather than a tap that wandered. */
const SWIPE_THRESHOLD = 0.2;

/** How many pictures from the end `onNearEnd` fires. */
const NEAR_END = 3;

/**
 * One picture at a time, full size, with the rest a swipe away.
 *
 * Built on the same dialog every other overlay uses, so it closes the same
 * ways — Escape, the button, a tap outside the picture — and stacks correctly
 * over whatever opened it. What it adds is paging: chevrons for a pointer,
 * arrow keys for a keyboard, and for a finger a drag that follows it, so the
 * next picture is pulled in rather than summoned by a button somebody has to
 * find on a phone. A single item is simply a picture with no way to page.
 *
 * The neighbours are fetched ahead of time — an `Image()` each — so arriving
 * at one is not the moment its bytes are first asked for.
 */
export const Lightbox = ({
  open,
  onOpenChange,
  items,
  index,
  onIndexChange,
  actions,
  onNearEnd,
}: LightboxProps) => {
  const { t } = useTranslation("common");
  const count = items.length;
  const current = items[index];
  const hasPrev = index > 0;
  const hasNext = index < count - 1;

  const goTo = useCallback(
    (next: number) => {
      if (next < 0 || next >= count) return;
      onIndexChange(next);
    },
    [count, onIndexChange]
  );

  // Keys work while the dialog is open, wherever focus happens to be inside it.
  useEffect(() => {
    if (!open) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "ArrowLeft") goTo(index - 1);
      else if (event.key === "ArrowRight") goTo(index + 1);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, index, goTo]);

  // The neighbours, ahead of time.
  useEffect(() => {
    if (!open) return;
    for (const neighbour of [items[index - 1], items[index + 1]]) {
      if (neighbour) new Image().src = neighbour.src;
    }
  }, [open, index, items]);

  useEffect(() => {
    if (open && onNearEnd && count > 0 && index >= count - NEAR_END) onNearEnd();
  }, [open, index, count, onNearEnd]);

  // The drag. `offset` is where the finger has taken the picture; released
  // past the threshold it becomes a page, otherwise it springs back.
  const stageRef = useRef<HTMLDivElement | null>(null);
  const [drag, setDrag] = useState<{ startX: number; offset: number } | null>(null);

  const onPointerDown = (event: React.PointerEvent) => {
    if (event.pointerType === "mouse") return;
    event.currentTarget.setPointerCapture(event.pointerId);
    setDrag({ startX: event.clientX, offset: 0 });
  };
  const onPointerMove = (event: React.PointerEvent) => {
    if (!drag) return;
    let offset = event.clientX - drag.startX;
    // Resistance at the ends, so the first and last picture say so by
    // refusing to go rather than by going nowhere.
    if ((offset > 0 && !hasPrev) || (offset < 0 && !hasNext)) offset /= 3;
    setDrag({ startX: drag.startX, offset });
  };
  const onPointerUp = () => {
    if (!drag) return;
    const width = stageRef.current?.clientWidth ?? 1;
    const share = drag.offset / width;
    setDrag(null);
    if (share <= -SWIPE_THRESHOLD && hasNext) goTo(index + 1);
    else if (share >= SWIPE_THRESHOLD && hasPrev) goTo(index - 1);
  };

  if (!current) return null;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        showCloseButton={false}
        className="flex h-[100dvh] max-h-[100dvh] w-screen max-w-[100vw] flex-col gap-0 rounded-none border-0 bg-black/95 p-0 text-white shadow-none sm:max-w-[100vw]"
      >
        <DialogTitle className="sr-only">{current.alt || t("lightbox.title")}</DialogTitle>
        <DialogDescription className="sr-only">{t("lightbox.description")}</DialogDescription>

        {/* Top bar: where you are, and what you can do about it. */}
        <div className="flex shrink-0 items-center justify-between gap-2 px-3 py-2">
          <span className="text-white/70 text-xs tabular-nums">
            {count > 1 ? t("lightbox.position", { current: index + 1, total: count }) : null}
          </span>
          <div className="flex items-center gap-1">
            {actions}
            <Button
              variant="ghost"
              size="icon"
              className="text-white hover:bg-white/10 hover:text-white"
              aria-label={t("close")}
              onClick={() => onOpenChange(false)}
            >
              <X className="size-5" />
            </Button>
          </div>
        </div>

        {/* The stage. `touch-action: pan-y` leaves vertical scrolling to the
            browser and takes horizontal for the swipe. */}
        <div
          ref={stageRef}
          className="relative flex min-h-0 flex-1 touch-pan-y select-none items-center justify-center overflow-hidden"
          onPointerDown={onPointerDown}
          onPointerMove={onPointerMove}
          onPointerUp={onPointerUp}
          onPointerCancel={() => setDrag(null)}
        >
          <img
            key={current.id}
            src={current.src}
            alt={current.alt}
            draggable={false}
            referrerPolicy="no-referrer"
            style={drag ? { transform: `translateX(${drag.offset}px)` } : undefined}
            className={cn(
              "max-h-full max-w-full object-contain",
              drag ? "transition-none" : "transition-transform duration-200 ease-out"
            )}
          />
          {hasPrev && (
            <Button
              variant="ghost"
              size="icon"
              aria-label={t("previous")}
              onClick={() => goTo(index - 1)}
              className="absolute left-2 hidden size-10 rounded-full bg-black/40 text-white hover:bg-black/60 hover:text-white sm:inline-flex"
            >
              <ChevronLeft className="size-6" />
            </Button>
          )}
          {hasNext && (
            <Button
              variant="ghost"
              size="icon"
              aria-label={t("next")}
              onClick={() => goTo(index + 1)}
              className="absolute right-2 hidden size-10 rounded-full bg-black/40 text-white hover:bg-black/60 hover:text-white sm:inline-flex"
            >
              <ChevronRight className="size-6" />
            </Button>
          )}
        </div>

        {current.caption ? (
          <div className="shrink-0 px-4 py-3 text-center text-sm text-white/80">
            {current.caption}
          </div>
        ) : null}
      </DialogContent>
    </Dialog>
  );
};
