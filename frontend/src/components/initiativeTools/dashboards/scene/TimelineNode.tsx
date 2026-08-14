import { useMemo } from "react";

import { formatAxisValue } from "@/lib/widgets/format";
import type { SceneNode } from "@/lib/widgets/sceneSpec";
import { toneColor } from "@/lib/widgets/tone";

type Node = Extract<SceneNode, { kind: "timeline" }>;

const LANE_LABEL_WIDTH = 110;
const ROW_HEIGHT = 22;
const TICKS = 5;

/**
 * Spans on a shared time axis — the Gantt shape.
 *
 * Drawn with positioned divs over a percentage-based axis so it reflows with
 * the tile instead of needing a measured width. Times arrive as epoch
 * milliseconds and are formatted here, in the viewer's locale and timezone —
 * the widget that produced them had neither.
 */
export function TimelineNode({ node }: { node: Node }) {
  const { start, end } = useMemo(() => {
    if (node.start !== undefined && node.end !== undefined && node.end > node.start) {
      return { start: node.start, end: node.end };
    }
    let low = Number.POSITIVE_INFINITY;
    let high = Number.NEGATIVE_INFINITY;
    for (const lane of node.lanes) {
      for (const span of lane.spans) {
        if (span.start < low) low = span.start;
        if (span.end > high) high = span.end;
      }
    }
    if (!Number.isFinite(low)) return { start: 0, end: 1 };
    // A single instant has no width to scale against; give it a day.
    return { start: low, end: high > low ? high : low + 86_400_000 };
  }, [node]);

  const span = end - start;
  const position = (value: number) => ((value - start) / span) * 100;

  const ticks = Array.from({ length: TICKS }, (_, index) => {
    const at = start + (span * index) / (TICKS - 1);
    return { at, label: formatAxisValue(at, "date") };
  });

  return (
    <div className="flex h-full w-full flex-col overflow-auto p-1">
      <div className="flex" style={{ paddingLeft: LANE_LABEL_WIDTH }}>
        {ticks.map((tick, index) => (
          <span
            key={tick.at}
            className="flex-1 text-muted-foreground text-xs"
            style={{ textAlign: index === ticks.length - 1 ? "right" : "left" }}
          >
            {tick.label}
          </span>
        ))}
      </div>

      <div className="flex flex-col gap-1">
        {node.lanes.map((lane, laneIndex) => (
          <div
            // biome-ignore lint/suspicious/noArrayIndexKey: lane labels may repeat (two projects of the same name), so position is the identity
            key={`${lane.label ?? "lane"}-${laneIndex}`}
            className="flex items-center gap-2"
            style={{ minHeight: ROW_HEIGHT }}
          >
            <span
              className="shrink-0 truncate text-muted-foreground text-xs"
              style={{ width: LANE_LABEL_WIDTH }}
              title={lane.label}
            >
              {lane.label}
            </span>
            <div className="relative h-4 flex-1 rounded-sm bg-muted/40">
              {lane.spans.map((barSpan, spanIndex) => {
                const left = position(barSpan.start);
                const width = Math.max(1, position(barSpan.end) - left);
                return (
                  <div
                    // biome-ignore lint/suspicious/noArrayIndexKey: two spans may share a start time, so position is the identity
                    key={`${barSpan.start}-${spanIndex}`}
                    className="absolute inset-y-0 overflow-hidden rounded-sm"
                    style={{
                      left: `${left}%`,
                      width: `${width}%`,
                      backgroundColor: toneColor(barSpan.tone),
                      opacity: 0.35,
                    }}
                    title={barSpan.label}
                  >
                    {barSpan.progress !== undefined && (
                      <div
                        className="h-full"
                        style={{
                          width: `${Math.min(1, Math.max(0, barSpan.progress)) * 100}%`,
                          backgroundColor: toneColor(barSpan.tone),
                        }}
                      />
                    )}
                  </div>
                );
              })}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
