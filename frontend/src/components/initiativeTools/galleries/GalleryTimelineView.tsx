import { useCallback, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import type { GalleryImageRead, TimelineBucket } from "@/api/generated/initiativeAPI.schemas";
import { GalleryImageTile } from "@/components/initiativeTools/galleries/GalleryImageTile";
import { type VirtualRow, VirtualRows } from "@/components/initiativeTools/galleries/VirtualRows";
import { TimelineRail } from "@/components/timeline/TimelineRail";
import type { GridToggleOptions } from "@/hooks/useGridSelection";
import { formatPeriod, formatPeriodYear } from "@/lib/formatDate";
import { aspectRatio, formatDay, groupByDay, imagePeriod } from "@/lib/galleries";

interface GalleryTimelineViewProps {
  images: GalleryImageRead[];
  /** The months the gallery has pictures in — what the rail is drawn from. */
  buckets: TimelineBucket[];
  onActivate: (image: GalleryImageRead, options: GridToggleOptions) => void;
  selecting?: boolean;
  isSelected?: (image: GalleryImageRead) => boolean;
  /** A month was picked on the rail. */
  onJump: (bucket: TimelineBucket) => void;
}

/** How tall a picture stands in a day's row. Pictures from the same day sit
 *  side by side at this height, each as wide as its shape makes it. */
const ROW_HEIGHT = 176;
const DAY_HEADING = 28;

/**
 * The gallery as a record: a row per day, newest first, and a rail down the
 * side for jumping months.
 *
 * Pictures uploaded on the same day sit side by side; a new day starts a new
 * row under its date. Which is the view a design round wants — the sequence
 * is the information, and a day's canvases beside each other say what that
 * round looked like.
 */
export const GalleryTimelineView = ({
  images,
  buckets,
  onActivate,
  selecting = false,
  isSelected,
  onJump,
}: GalleryTimelineViewProps) => {
  const { t } = useTranslation("galleries");
  const days = useMemo(() => groupByDay(images), [images]);

  const rows = useMemo<VirtualRow[]>(
    () =>
      days.map((group) => ({
        key: group.day,
        // A heading plus however many rows of pictures the day wraps to.
        estimate: DAY_HEADING + ROW_HEIGHT * Math.ceil(group.items.length / 4),
        render: () => (
          <section aria-label={formatDay(group.day)}>
            <h3 className="pb-2 font-medium text-muted-foreground text-xs uppercase tracking-wide">
              {formatDay(group.day)}
              <span className="ml-2 font-normal normal-case tracking-normal">
                {t("groups.count", { count: group.items.length })}
              </span>
            </h3>
            <div className="flex flex-wrap gap-2">
              {group.items.map((image) => (
                <GalleryImageTile
                  key={image.id}
                  image={image}
                  fit="shape"
                  onActivate={(options) => onActivate(image, options)}
                  selecting={selecting}
                  selected={isSelected?.(image) ?? false}
                  className="max-w-full"
                  style={{
                    height: ROW_HEIGHT,
                    width: Math.round(ROW_HEIGHT * (aspectRatio(image) ?? 4 / 3)),
                  }}
                />
              ))}
            </div>
          </section>
        ),
      })),
    [days, onActivate, selecting, isSelected, t]
  );

  // The month at the top of the view, so the rail marks where the reader is.
  const [activeDay, setActiveDay] = useState<string | null>(null);
  const onFirstVisible = useCallback(
    (index: number) => setActiveDay(days[index]?.day ?? null),
    [days]
  );
  const activePeriod = useMemo(() => {
    const day = activeDay ?? days[0]?.day;
    if (!day) return null;
    const image = days.find((group) => group.day === day)?.items[0];
    return image ? imagePeriod(image) : null;
  }, [activeDay, days]);

  return (
    <div className="flex gap-3">
      <div className="min-w-0 flex-1">
        <VirtualRows rows={rows} onFirstVisible={onFirstVisible} />
      </div>
      <TimelineRail
        stops={buckets}
        activePeriod={activePeriod}
        onPick={onJump}
        formatLabel={(stop) => formatPeriod(stop.period)}
        formatGroup={(stop) => formatPeriodYear(stop.period)}
        className="sticky top-4 h-[70vh] self-start"
      />
    </div>
  );
};
