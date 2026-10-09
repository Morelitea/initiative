/**
 * Built-in: Stat — one big number, and what it is doing.
 *
 * The trend is why the widget is more than a number in a box. When the binding
 * is bucketed by day, the rows *are* a time series, so the widget splits them
 * into two halves and reports the later against the earlier — which is what
 * anyone reading a dashboard actually wants to know.
 *
 * Its template draws the number alone, or above its own history as a
 * sparkline when the trend is on and there is history to draw.
 */

import type { MetricNode, SeriesNode } from "../sceneSpec";
import type { WidgetMeta } from "../widgetMeta";
import { type BuiltinWidget, empty, sayer, type WidgetStrings } from "./builtin";
import template from "./stat.widget.html?template";

/** What this widget calls itself, in every language it supports. */
const meta: WidgetMeta = {
  name: {
    en: "Stat",
    de: "Kennzahl",
    es: "Estadística",
    fr: "Statistique",
  },
  description: {
    en: "A single headline number, with an optional trend against the previous period.",
    de: "Eine einzelne Kennzahl, wahlweise mit Trend gegenüber dem Vorzeitraum.",
    es: "Una única cifra destacada, con una tendencia opcional respecto al periodo anterior.",
    fr: "Un seul chiffre clé, avec une tendance facultative par rapport à la période précédente.",
  },
  options: {
    format: {
      label: {
        en: "Format",
        de: "Format",
        es: "Formato",
        fr: "Format",
      },
      values: {
        plain: {
          en: "Plain number",
          de: "Einfache Zahl",
          es: "Número simple",
          fr: "Nombre simple",
        },
        percent: {
          en: "Percentage",
          de: "Prozent",
          es: "Porcentaje",
          fr: "Pourcentage",
        },
        currency: {
          en: "Currency",
          de: "Währung",
          es: "Moneda",
          fr: "Devise",
        },
        duration: {
          en: "Duration",
          de: "Dauer",
          es: "Duración",
          fr: "Durée",
        },
      },
    },
    pick: {
      label: {
        en: "Which number",
        de: "Welche Zahl",
        es: "Qué número",
        fr: "Quel chiffre",
      },
      values: {
        total: {
          en: "Total of everything",
          de: "Summe von allem",
          es: "Total de todo",
          fr: "Total de tout",
        },
        largest: {
          en: "The largest group",
          de: "Die größte Gruppe",
          es: "El grupo más grande",
          fr: "Le plus grand groupe",
        },
        first: {
          en: "The first group",
          de: "Die erste Gruppe",
          es: "El primer grupo",
          fr: "Le premier groupe",
        },
      },
    },
    trend: {
      label: {
        en: "Trend",
        de: "Trend",
        es: "Tendencia",
        fr: "Tendance",
      },
      values: {
        off: {
          en: "Just the number",
          de: "Nur die Zahl",
          es: "Solo el número",
          fr: "Le chiffre seul",
        },
        on: {
          en: "Show change and a sparkline",
          de: "Veränderung und Verlaufslinie zeigen",
          es: "Mostrar el cambio y una minigráfica",
          fr: "Afficher l'évolution et une courbe",
        },
      },
    },
    direction: {
      label: {
        en: "Rising is",
        de: "Steigend ist",
        es: "Subir es",
        fr: "En hausse, c'est",
      },
      values: {
        up_good: {
          en: "Good",
          de: "Gut",
          es: "Bueno",
          fr: "Bon",
        },
        down_good: {
          en: "Bad",
          de: "Schlecht",
          es: "Malo",
          fr: "Mauvais",
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
    en: "No numeric column to report",
    de: "Keine Zahlenspalte zum Anzeigen",
    es: "Ninguna columna numérica que mostrar",
    fr: "Aucune colonne numérique à afficher",
  },
  total: { en: "Total", de: "Gesamt", es: "Total", fr: "Total" },
  of: { en: "of", de: "von", es: "de", fr: "sur" },
  points: { en: "points", de: "Punkte", es: "puntos", fr: "points" },
};

/** The number, and the points of its history when the template should draw them. */
type StatModel = MetricNode & { sparkline?: SeriesNode["series"] };

/** Later half against earlier half, as a fraction. Null when there is not
 *  enough history to make the comparison mean anything — a made-up baseline
 *  would read as a real one. */
const changeOver = (values: number[]): number | null => {
  if (values.length < 4) return null;
  const middle = Math.floor(values.length / 2);
  let earlier = 0;
  let later = 0;
  for (let index = 0; index < middle; index++) earlier += values[index] as number;
  for (let index = middle; index < values.length; index++) later += values[index] as number;
  if (earlier <= 0) return null;
  return (later - earlier) / earlier;
};

const shape: BuiltinWidget["shape"] = (data, config, context) => {
  const say = sayer(strings, context.locale);
  const format = (config.format || "plain") as MetricNode["format"];
  const pick = config.pick || "total";
  const wantTrend = config.trend === "on";
  const deltaGood = config.direction === "down_good" ? "down" : "up";

  const metric = (
    value: number,
    label?: string,
    caption?: string,
    extra?: Partial<MetricNode>
  ): StatModel => ({
    kind: "metric",
    value: Number.isFinite(value) ? value : 0,
    label: label || undefined,
    caption: caption || undefined,
    format,
    ...extra,
  });

  // Which columns fill this widget's slots, resolved by the host.
  const slots = context.slots ?? {};
  const valueAt = slots.value?.[0];
  const labelAt = slots.label?.[0];

  const rows = data.rows ?? [];
  if (!rows.length) return empty(say("noRows"));
  if (valueAt === undefined) return empty(say("noNumeric"));

  const number = (row: (typeof rows)[number]) =>
    typeof row[valueAt] === "number" ? (row[valueAt] as number) : 0;
  const name = (row: (typeof rows)[number]) =>
    labelAt !== undefined && row[labelAt] !== null ? String(row[labelAt]) : undefined;
  const values = rows.map(number);
  const total = values.reduce((sum, value) => sum + value, 0);
  const heading = data.columns?.[valueAt]?.name;

  // A label that orders — a date — makes this a time series: report the total,
  // say how it moved, and draw the shape underneath. A label that does not
  // order has no sequence to read a change from, so none is claimed.
  const overTime = labelAt !== undefined && data.columns?.[labelAt]?.type === "date";

  if (overTime) {
    const ordered = rows
      .slice()
      .sort((a, b) => ((a[labelAt] as number) || 0) - ((b[labelAt] as number) || 0));
    const change = changeOver(ordered.map(number));
    const node = metric(
      total,
      heading,
      `${ordered.length} ${say("points")}`,
      change === null ? undefined : { delta: change, deltaGood }
    );
    // The number leads; its history is context under it.
    if (!wantTrend || ordered.length < 3) return node;
    const points = ordered.map((row, index) => ({ x: index + 1, y: number(row) }));
    return { ...node, sparkline: [{ name: node.label || "", points, tone: "accent" }] };
  }

  if (pick === "largest") {
    let best = rows[0] as (typeof rows)[number];
    for (const row of rows) if (number(row) > number(best)) best = row;
    return metric(number(best), name(best) || heading, `${say("of")} ${total}`);
  }
  if (pick === "first") {
    const first = rows[0] as (typeof rows)[number];
    return metric(number(first), name(first) || heading, `${say("of")} ${total}`);
  }
  return metric(total, heading || say("total"));
};

export const stat: BuiltinWidget = { meta, shape, template };
