/**
 * Built-in: chart — a series drawn as bars, lines, an area, or slices.
 *
 * The workhorse: the `bar_chart`/`line_chart`/`area_chart`/`pie_chart`/
 * `stacked_bar_chart` presets are all this widget with a fixed `mark`.
 *
 * What it grew: an order, a category ceiling, a direction, selective value
 * labels, and emphasis. The ceiling is the one worth explaining — past its slot
 * count a categorical palette has no more distinguishable colors, so a chart
 * with thirty projects on it cannot be read however it is drawn. Folding the
 * tail into one "Other" is the honest answer; inventing a thirtieth color is
 * not.
 */

import type { CellValue } from "../dataShapes";
import type {
  Series,
  SeriesLabels,
  SeriesMark,
  SeriesNode,
  SeriesPoint,
  SeriesTimeUnit,
} from "../sceneSpec";
import type { WidgetMeta } from "../widgetMeta";
import { type BuiltinWidget, empty, sayer, type WidgetStrings } from "./builtin";
import template from "./chart.widget.html?template";

/** What this widget calls itself, in every language it supports. */
const meta: WidgetMeta = {
  name: {
    en: "Chart",
    de: "Diagramm",
    es: "Gráfico",
    fr: "Graphique",
  },
  description: {
    en: "A series drawn as bars, a line, a filled area, or slices of a whole.",
    de: "Eine Datenreihe als Balken, Linie, gefüllte Fläche oder Kreisdiagramm.",
    es: "Una serie dibujada como barras, línea, área rellena o porciones de un total.",
    fr: "Une série affichée en barres, en courbe, en aire remplie ou en parts d'un tout.",
  },
  options: {
    mark: {
      label: {
        en: "Chart type",
        de: "Diagrammtyp",
        es: "Tipo de gráfico",
        fr: "Type de graphique",
      },
      values: {
        bar: {
          en: "Bar",
          de: "Balken",
          es: "Barras",
          fr: "Barres",
        },
        line: {
          en: "Line",
          de: "Linie",
          es: "Líneas",
          fr: "Courbe",
        },
        area: {
          en: "Area",
          de: "Fläche",
          es: "Área",
          fr: "Aire",
        },
        pie: {
          en: "Pie",
          de: "Kreis",
          es: "Circular",
          fr: "Secteurs",
        },
      },
    },
    stacked: {
      label: {
        en: "Stacked",
        de: "Gestapelt",
        es: "Apilado",
        fr: "Empilé",
      },
      values: {
        true: {
          en: "Stacked",
          de: "Gestapelt",
          es: "Apilado",
          fr: "Empilé",
        },
        false: {
          en: "Side by side",
          de: "Nebeneinander",
          es: "Lado a lado",
          fr: "Côte à côte",
        },
      },
    },
    sort: {
      label: { en: "Order", de: "Reihenfolge", es: "Orden", fr: "Ordre" },
      values: {
        source: {
          en: "As the data comes",
          de: "Wie die Daten kommen",
          es: "Según llegan los datos",
          fr: "Dans l'ordre des données",
        },
        value_desc: {
          en: "Largest first",
          de: "Größte zuerst",
          es: "Mayor primero",
          fr: "Le plus grand d'abord",
        },
        value_asc: {
          en: "Smallest first",
          de: "Kleinste zuerst",
          es: "Menor primero",
          fr: "Le plus petit d'abord",
        },
        label: {
          en: "By name",
          de: "Nach Name",
          es: "Por nombre",
          fr: "Par nom",
        },
      },
    },
    limit: {
      label: {
        en: "How many categories",
        de: "Wie viele Kategorien",
        es: "Cuántas categorías",
        fr: "Combien de catégories",
      },
      values: {
        all: { en: "All of them", de: "Alle", es: "Todas", fr: "Toutes" },
        5: {
          en: "Top 5, rest as Other",
          de: "Top 5, Rest als Sonstige",
          es: "Las 5 mayores, resto como Otros",
          fr: "Les 5 premières, reste en Autres",
        },
        8: {
          en: "Top 8, rest as Other",
          de: "Top 8, Rest als Sonstige",
          es: "Las 8 mayores, resto como Otros",
          fr: "Les 8 premières, reste en Autres",
        },
        12: {
          en: "Top 12, rest as Other",
          de: "Top 12, Rest als Sonstige",
          es: "Las 12 mayores, resto como Otros",
          fr: "Les 12 premières, reste en Autres",
        },
      },
    },
    orientation: {
      label: { en: "Direction", de: "Ausrichtung", es: "Dirección", fr: "Orientation" },
      values: {
        columns: {
          en: "Columns",
          de: "Säulen",
          es: "Columnas",
          fr: "Colonnes",
        },
        bars: {
          en: "Bars, for long names",
          de: "Balken, für lange Namen",
          es: "Barras, para nombres largos",
          fr: "Barres, pour les noms longs",
        },
      },
    },
    values: {
      label: {
        en: "Show values on",
        de: "Werte anzeigen bei",
        es: "Mostrar valores en",
        fr: "Afficher les valeurs sur",
      },
      values: {
        none: { en: "Nothing", de: "Nichts", es: "Nada", fr: "Rien" },
        extremes: {
          en: "The highest and lowest",
          de: "Höchster und niedrigster Wert",
          es: "El mayor y el menor",
          fr: "Le plus haut et le plus bas",
        },
        end: {
          en: "The last point",
          de: "Dem letzten Punkt",
          es: "El último punto",
          fr: "Le dernier point",
        },
      },
    },
    emphasis: {
      label: { en: "Highlight", de: "Hervorheben", es: "Destacar", fr: "Mettre en avant" },
      values: {
        none: {
          en: "Nothing — every series in color",
          de: "Nichts – alle Reihen farbig",
          es: "Nada: todas las series en color",
          fr: "Rien — toutes les séries en couleur",
        },
        largest: {
          en: "The largest series",
          de: "Die größte Reihe",
          es: "La serie mayor",
          fr: "La plus grande série",
        },
        last: {
          en: "The last series",
          de: "Die letzte Reihe",
          es: "La última serie",
          fr: "La dernière série",
        },
      },
    },
  },
};

/** This widget's own words, in every language it speaks. */
const strings: WidgetStrings = {
  noRows: {
    en: "Nothing to show",
    de: "Nichts anzuzeigen",
    es: "Nada que mostrar",
    fr: "Rien à afficher",
  },
  noNumeric: {
    en: "No numeric column to plot",
    de: "Keine Zahlenspalte zum Zeichnen",
    es: "Ninguna columna numérica que representar",
    fr: "Aucune colonne numérique à tracer",
  },
  other: { en: "Other", de: "Sonstige", es: "Otros", fr: "Autres" },
  series: { en: "Series", de: "Reihe", es: "Serie", fr: "Série" },
};

/** The periods a date label can be rounded to. */
const GRAINS: readonly SeriesTimeUnit[] = ["day", "week", "month", "quarter", "year"];

/** One category, and its total across every series. */
interface Category {
  x: SeriesPoint["x"];
  total: number;
}

const shape: BuiltinWidget["shape"] = (data, config, context) => {
  const say = sayer(strings, context.locale);
  const mark = (config.mark || "bar") as SeriesMark;
  const stacked = config.stacked === "true";
  const sort = config.sort || "source";
  const limit = config.limit === "all" || !config.limit ? 0 : Number(config.limit) || 0;
  const horizontal = config.orientation === "bars";
  const labels =
    config.values && config.values !== "none" ? (config.values as SeriesLabels) : undefined;
  const emphasis = config.emphasis || "none";

  /** What the folded tail is called. */
  const OTHER_LABEL = say("other");

  /** Which series gets to keep its color when the rest go gray. */
  const emphasisIndex = (series: Series[]): number | undefined => {
    if (emphasis === "none" || series.length < 2) return undefined;
    if (emphasis === "last") return series.length - 1;
    let best = 0;
    let bestTotal = -Infinity;
    for (const [index, entry] of series.entries()) {
      let total = 0;
      for (const point of entry.points) total += point.y;
      if (total > bestTotal) {
        bestTotal = total;
        best = index;
      }
    }
    return best;
  };

  /**
   * Order the categories and cap how many are drawn — once, across every
   * series.
   *
   * Arranging each series on its own looks equivalent and is not: two series
   * sorted by their own values disagree about the order, and two series capped
   * on their own keep *different* categories, so the merged chart silently
   * drops the halves that did not survive on both sides. The cut is therefore
   * made on each category's total across all series, and every series is then
   * mapped onto that one shared order.
   *
   * Pie slices always read as a share of a whole, so the largest belongs first
   * whatever the chosen order says; everything else keeps the order asked for,
   * and "source" is meaningful more often than not (a day sequence, a workflow
   * order).
   */
  const arrangeAll = (list: Series[]): Series[] => {
    const totals = new Map<string, Category>();
    const seen: Category[] = [];
    for (const series of list) {
      for (const point of series.points) {
        const key = String(point.x);
        let entry = totals.get(key);
        if (!entry) {
          entry = { x: point.x, total: 0 };
          totals.set(key, entry);
          seen.push(entry);
        }
        entry.total += point.y;
      }
    }

    let order = seen;
    if (sort === "value_desc" || mark === "pie") {
      order = seen.slice().sort((a, b) => b.total - a.total);
    } else if (sort === "value_asc") {
      order = seen.slice().sort((a, b) => a.total - b.total);
    } else if (sort === "label") {
      order = seen.slice().sort((a, b) => String(a.x).localeCompare(String(b.x)));
    }

    // The tail becomes one category rather than more colors, chosen by total so
    // "Other" is genuinely the small remainder.
    let kept = order;
    let keptKeys: Set<string> | null = null;
    if (limit && order.length > limit) {
      const byValue = order.slice().sort((a, b) => b.total - a.total);
      const keep = new Set(byValue.slice(0, limit).map((entry) => String(entry.x)));
      // A category genuinely called "Other" joins the fold instead of sitting
      // beside it. A chart has one bar per label and the renderer merges points
      // by label, so two of them would not draw as two — one would quietly
      // replace the other. Folding the collider keeps every value counted, and
      // it is reachable in practice: the label is translated, so a project
      // named "Sonstige" collides for a German reader and not for an English
      // one.
      keep.delete(OTHER_LABEL);
      kept = order.filter((entry) => keep.has(String(entry.x)));
      keptKeys = keep;
    }

    return list.map((series) => {
      const byX = new Map<string, number>();
      for (const point of series.points) byX.set(String(point.x), point.y);

      const points: SeriesPoint[] = [];
      for (const entry of kept) {
        const y = byX.get(String(entry.x));
        // A category this series never had stays absent rather than becoming a
        // zero it never reported; the renderer merges on x and leaves the gap.
        if (y !== undefined) points.push({ x: entry.x, y });
      }
      if (keptKeys) {
        // Every series folds its own tail, so the "Other" bar is whole rather
        // than one series' share of it. Zero is the true value for a series
        // with nothing in the tail.
        let rest = 0;
        for (const point of series.points) {
          if (!keptKeys.has(String(point.x))) rest += point.y;
        }
        points.push({ x: OTHER_LABEL, y: rest });
      }

      const arranged: Series = { name: series.name, points };
      if (series.tone) arranged.tone = series.tone;
      return arranged;
    });
  };

  // Which columns fill this widget's slots, resolved by the host. `value` is
  // repeatable, so a statement returning several numbers draws several series
  // without the author saying so twice.
  const slots = context.slots ?? {};
  const labelAt = slots.label?.[0];
  const valueColumns = slots.value ?? [];

  const rows = data.rows ?? [];
  if (!rows.length) return empty(say("noRows"));
  if (!valueColumns.length) return empty(say("noNumeric"));

  const columns = data.columns ?? [];
  const nameOf = (index: number): string => {
    const column = columns[index];
    return column ? column.name : say("series");
  };

  // A date label is a moment in epoch milliseconds. It stays a number, and the
  // scene says which period each point is — the unit the statement rounded
  // the column to, or a day for a plain date — so the app can label it
  // "Mar 2026" or "Q1 2026" rather than printing the raw number.
  const labelColumn = labelAt !== undefined ? columns[labelAt] : undefined;
  const xTime: SeriesTimeUnit | undefined =
    labelColumn && labelColumn.type === "date"
      ? labelColumn.grain && GRAINS.includes(labelColumn.grain)
        ? labelColumn.grain
        : "day"
      : undefined;

  const labelOf = (row: CellValue[], rowIndex: number): SeriesPoint["x"] => {
    if (labelAt === undefined || row[labelAt] === null) return rowIndex + 1;
    if (xTime && typeof row[labelAt] === "number") return row[labelAt] as number;
    return String(row[labelAt]);
  };

  const series: Series[] = valueColumns.slice(0, 12).map((index) => ({
    name: nameOf(index),
    points: rows.map((row, rowIndex) => ({
      x: labelOf(row, rowIndex),
      y: typeof row[index] === "number" ? (row[index] as number) : 0,
    })),
  }));

  const arranged = arrangeAll(series);
  return {
    kind: "series",
    mark,
    series: arranged,
    stacked: stacked || undefined,
    xLabel: labelColumn?.name || undefined,
    xTime,
    // A legend earns its space only once there is more than one series.
    showLegend: arranged.length > 1,
    labels,
    horizontal: horizontal && mark === "bar" ? true : undefined,
    emphasis: emphasisIndex(arranged),
  } satisfies SeriesNode;
};

export const chart: BuiltinWidget = { meta, shape, template };
