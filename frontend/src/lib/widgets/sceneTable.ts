/**
 * Every scene, as a table.
 *
 * A chart that can only be read by looking at it is a chart some people cannot
 * read at all — and a tooltip is not a remedy, because it gates the value
 * behind a pointer. The remedy is a table with the same numbers in it.
 *
 * The leverage is *where* this sits. It derives from the validated `SceneSpec`,
 * not from the widget, so one implementation gives a tabular twin to every
 * widget — the built-ins, and equally a marketplace widget nobody here has
 * seen, with no cooperation required from either. A widget author cannot
 * forget to provide it and cannot opt out of it.
 *
 * Output is `TableNode`s, which is the vocabulary the trusted table renderer
 * already draws. A `stack` becomes one table per child rather than a merged
 * grid: the children are separate pictures, and interleaving their rows would
 * invent a relationship the scene never claimed.
 */

import type { TFunction } from "i18next";

import type { SceneNode, TableCell, TableColumn, TimelineLane } from "@/lib/widgets/sceneSpec";

type TableScene = Extract<SceneNode, { kind: "table" }>;

export type SceneTableT = TFunction<["dashboards", "common"]>;

const table = (columns: TableColumn[], rows: Record<string, TableCell>[]): TableScene => ({
  kind: "table",
  columns,
  rows,
});

/** Lanes carry their nesting in the label, since a table has no fold. The
 *  indent is text, so it survives copy-paste and a screen reader reads it as
 *  part of the name rather than as layout. */
const flattenLanes = (
  lanes: TimelineLane[],
  depth: number,
  into: Record<string, TableCell>[]
): void => {
  for (const lane of lanes) {
    const first = lane.spans[0];
    into.push({
      lane: `${"— ".repeat(depth)}${lane.label ?? ""}`.trimEnd(),
      start: first?.start ?? null,
      end: first?.end ?? null,
      progress: first?.progress ?? null,
      caption: lane.caption ?? null,
    });
    if (lane.children?.length) flattenLanes(lane.children, depth + 1, into);
  }
};

/**
 * One scene as one or more tables.
 *
 * Returns an empty list for a scene with nothing in it — the caller draws the
 * scene's own empty state rather than an empty grid.
 */
export function sceneToTables(node: SceneNode, t: SceneTableT): TableScene[] {
  switch (node.kind) {
    case "table":
      return [node];

    case "metric":
      return [
        table(
          [
            { key: "label", label: t("dashboards:tableView.label") },
            {
              key: "value",
              label: t("dashboards:tableView.value"),
              align: "end",
              format: node.format,
            },
          ],
          [{ label: node.label ?? node.caption ?? "", value: node.value }]
        ),
      ];

    case "series": {
      // One row per x, one column per series — the same merge the chart does,
      // so the table and the picture agree row for row.
      const order: (string | number)[] = [];
      const byX = new Map<string | number, Record<string, TableCell>>();
      node.series.forEach((series, index) => {
        for (const point of series.points) {
          let row = byX.get(point.x);
          if (!row) {
            row = { x: point.x };
            byX.set(point.x, row);
            order.push(point.x);
          }
          row[`s${index}`] = point.y;
        }
      });
      const columns: TableColumn[] = [
        { key: "x", label: node.xLabel ?? t("dashboards:tableView.category") },
        ...node.series.map((series, index) => ({
          key: `s${index}`,
          label: series.name ?? `${t("dashboards:tableView.series")} ${index + 1}`,
          align: "end" as const,
          format: node.format,
        })),
      ];
      return [
        table(
          columns,
          order.map((x) => byX.get(x) as Record<string, TableCell>)
        ),
      ];
    }

    case "timeline": {
      const rows: Record<string, TableCell>[] = [];
      flattenLanes(node.lanes, 0, rows);
      return [
        table(
          [
            { key: "lane", label: t("dashboards:tableView.lane") },
            { key: "start", label: t("dashboards:tableView.start"), align: "end", format: "date" },
            { key: "end", label: t("dashboards:tableView.end"), align: "end", format: "date" },
            {
              key: "progress",
              label: t("dashboards:tableView.progress"),
              align: "end",
              format: "percent",
            },
          ],
          rows
        ),
      ];
    }

    case "funnel":
      return [
        table(
          [
            { key: "stage", label: t("dashboards:tableView.stage") },
            {
              key: "value",
              label: t("dashboards:tableView.value"),
              align: "end",
              format: node.format,
            },
          ],
          node.stages.map((stage) => ({ stage: stage.label, value: stage.value }))
        ),
      ];

    case "progress":
      return [
        table(
          [
            { key: "label", label: t("dashboards:tableView.label") },
            {
              key: "value",
              label: t("dashboards:tableView.value"),
              align: "end",
              format: node.format,
            },
          ],
          [{ label: node.label ?? node.caption ?? "", value: node.value }]
        ),
      ];

    case "matrix":
      return [
        table(
          [
            { key: "x", label: node.xLabels?.length ? "" : t("dashboards:tableView.column") },
            { key: "y", label: t("dashboards:tableView.lane") },
            { key: "value", label: t("dashboards:tableView.value"), align: "end" },
          ],
          node.cells.map((cell) => ({
            x: node.xLabels?.[cell.x] ?? cell.x,
            y: node.yLabels?.[cell.y] ?? cell.y,
            value: cell.value,
          }))
        ),
      ];

    case "text":
      return [
        table([{ key: "text", label: t("dashboards:tableView.label") }], [{ text: node.text }]),
      ];

    case "stack":
      return node.children.flatMap((child) => sceneToTables(child, t));

    default:
      return [];
  }
}
