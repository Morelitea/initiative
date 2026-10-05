/**
 * Where a community is, on a row of its own.
 *
 * The row is the short reading ("Queen Anne Neighborhood, Seattle, WA") and is
 * cut to one line wherever it sits. Anything it left out — a street, a
 * postcode, the region or country it abbreviated — is a hover or a tap away,
 * along with a link to find it on a map. A location the row already says in
 * full is plain text: there is nothing to open.
 */

import { ExternalLink, MapPin } from "lucide-react";
import { type CSSProperties, type PointerEvent, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import {
  type CommunityLocation,
  locationDetailLines,
  locationHasMoreDetail,
  locationLine,
  locationMapUrl,
  locationPlace,
} from "@/lib/communityLocation";
import { cn } from "@/lib/utils";

export type CommunityLocationLineProps = {
  location: CommunityLocation;
  className?: string;
  /** For a row painted on a banner, in the banner's own ink. */
  style?: CSSProperties;
};

/** How long the pointer may be off both the row and its details before they close. */
const HOVER_CLOSE_DELAY = 150;

export const CommunityLocationLine = ({
  location,
  className,
  style,
}: CommunityLocationLineProps) => {
  const { t, i18n } = useTranslation("communities");
  const locale = i18n.resolvedLanguage ?? i18n.language ?? "en";
  const [open, setOpen] = useState(false);
  const closeTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  // Opened by a click or a tap, which only a dismissal closes — not the
  // pointer wandering off.
  const pinned = useRef(false);

  const line = locationLine(location, locale);
  const label = t("location.ariaLabel", { location: line });
  const rowClass = cn("flex min-w-0 max-w-full items-center gap-1 text-xs", className);
  const place = locationPlace(location, locale);
  const ownName = location.label?.trim();
  // When the row runs out of room the community's own name for the place gives
  // way first, so "Seattle, WA" survives a long neighbourhood name.
  const content = (
    <>
      <MapPin className="size-[1em] shrink-0" aria-hidden="true" />
      {ownName ? <span className="min-w-0 shrink truncate">{ownName},</span> : null}
      <span className="min-w-0 shrink-[0.001] truncate">{place}</span>
    </>
  );

  if (!locationHasMoreDetail(location)) {
    return (
      <p className={rowClass} style={style} title={line}>
        <span className="sr-only">{label}</span>
        <span aria-hidden="true" className="contents">
          {content}
        </span>
      </p>
    );
  }

  // A mouse opens it by resting on the row; a click or a tap pins it open, and
  // hover never closes a pinned one.
  const cancelClose = () => {
    if (closeTimer.current) clearTimeout(closeTimer.current);
    closeTimer.current = null;
  };
  const hoverOpen = (event: PointerEvent) => {
    if (event.pointerType !== "mouse") return;
    cancelClose();
    setOpen(true);
  };
  const hoverClose = (event: PointerEvent) => {
    if (event.pointerType !== "mouse" || pinned.current) return;
    cancelClose();
    closeTimer.current = setTimeout(() => setOpen(false), HOVER_CLOSE_DELAY);
  };

  return (
    <Popover
      open={open}
      onOpenChange={(next) => {
        if (!next) pinned.current = false;
        setOpen(next);
      }}
    >
      <PopoverTrigger asChild>
        <button
          type="button"
          className={cn(
            rowClass,
            "cursor-pointer rounded-sm text-left underline-offset-2 hover:underline focus-visible:outline-2 focus-visible:outline-current"
          )}
          style={style}
          title={line}
          aria-label={label}
          onPointerEnter={hoverOpen}
          onPointerLeave={hoverClose}
          // Hover has usually opened it already, so a click pins rather than
          // toggles; preventing the default stops the trigger's own toggle.
          onClick={(event) => {
            event.preventDefault();
            cancelClose();
            pinned.current = true;
            setOpen(true);
          }}
        >
          {content}
        </button>
      </PopoverTrigger>
      <PopoverContent
        align="start"
        className="w-64 space-y-2 p-3 text-sm"
        onPointerEnter={hoverOpen}
        onPointerLeave={hoverClose}
        // Opening on hover must not pull focus off whatever the reader was in.
        onOpenAutoFocus={(event) => event.preventDefault()}
      >
        <address className="space-y-0.5 not-italic">
          {locationDetailLines(location, locale).map((detail) => (
            <p
              key={detail.part}
              className={detail.part === "label" ? "font-medium" : "text-muted-foreground"}
            >
              {detail.text}
            </p>
          ))}
        </address>
        <a
          href={locationMapUrl(location, locale)}
          target="_blank"
          rel="noopener noreferrer"
          className="inline-flex items-center gap-1 text-primary text-xs hover:underline"
        >
          {t("location.openMap")}
          <ExternalLink className="h-3 w-3" aria-hidden="true" />
        </a>
      </PopoverContent>
    </Popover>
  );
};
