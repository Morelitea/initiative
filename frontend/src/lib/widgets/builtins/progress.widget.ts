/**
 * Built-in: progress — a meter, or a column of them.
 *
 * A meter answers "how far along, against what?", which needs both ends of the
 * range stated. A counter brings its own (its min and max); a set of tasks
 * brings a denominator; a project brings both plus, where it has an end date,
 * an idea of where it *should* be by now — drawn as a target mark so the fill
 * reads against the plan rather than against the bar's own end.
 *
 * Its template draws one meter on its own, or a list of them stacked.
 */

import type { CellValue } from "../dataShapes";
import type { ProgressNode, Tone } from "../sceneSpec";
import type { WidgetMeta } from "../widgetMeta";
import { type BuiltinWidget, empty, sayer, type WidgetStrings } from "./builtin";
import template from "./progress.widget.html?template";

/** What this widget calls itself, in every language it supports. */
const meta: WidgetMeta = {
  name: {
    en: "Progress",
    de: "Fortschritt",
    es: "Progreso",
    fr: "Progression",
  },
  description: {
    en: "How far a value has come against its own range.",
    de: "Wie weit ein Wert innerhalb seines Wertebereichs fortgeschritten ist.",
    es: "Cuánto ha avanzado un valor dentro de su propio rango.",
    fr: "La progression d'une valeur au sein de sa propre plage.",
  },
  options: {
    breakdown: {
      label: { en: "Show", de: "Anzeigen", es: "Mostrar", fr: "Afficher" },
      values: {
        total: {
          en: "One bar for everything",
          de: "Ein Balken für alles",
          es: "Una barra para todo",
          fr: "Une barre pour l'ensemble",
        },
        each: {
          en: "A bar for each",
          de: "Ein Balken je Eintrag",
          es: "Una barra por cada uno",
          fr: "Une barre pour chacun",
        },
      },
    },
    format: {
      label: { en: "Format", de: "Format", es: "Formato", fr: "Format" },
      values: {
        percent: {
          en: "Percentage",
          de: "Prozent",
          es: "Porcentaje",
          fr: "Pourcentage",
        },
        plain: {
          en: "Plain number",
          de: "Einfache Zahl",
          es: "Número simple",
          fr: "Nombre simple",
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
    en: "No numeric column to measure",
    de: "Keine Zahlenspalte zum Messen",
    es: "Ninguna columna numérica que medir",
    fr: "Aucune colonne numérique à mesurer",
  },
  row: { en: "Row", de: "Zeile", es: "Fila", fr: "Ligne" },
  total: { en: "Total", de: "Gesamt", es: "Total", fr: "Total" },
  done: { en: "Done", de: "Erledigt", es: "Hecho", fr: "Terminé" },
  of: { en: "of", de: "von", es: "de", fr: "sur" },
};

/** Several meters, for the template to stack. */
interface ProgressList {
  kind: "list";
  items: ProgressNode[];
}

type Row = CellValue[];

const shape: BuiltinWidget["shape"] = (data, config, context) => {
  const say = sayer(strings, context.locale);
  const each = config.breakdown === "each";
  const format: ProgressNode["format"] = config.format === "plain" ? "plain" : "percent";

  const meter = (
    label: string,
    value: number,
    min: number,
    max: number,
    caption: string,
    tone: Tone,
    target?: number
  ): ProgressNode => {
    const node: ProgressNode = {
      kind: "progress",
      value,
      min,
      max,
      label: label || undefined,
      caption: caption || undefined,
      tone: tone || undefined,
      format,
    };
    if (typeof target === "number") node.target = target;
    return node;
  };

  /** Several meters stacked. One is drawn on its own — a stack of one is a
   *  wrapper with nothing to compose. */
  const column = (nodes: ProgressNode[]) => {
    if (nodes.length === 1) return nodes[0] as ProgressNode;
    return { kind: "list", items: nodes.slice(0, 12) } satisfies ProgressList;
  };

  const shareTone = (done: number, total: number, late: boolean): Tone => {
    if (total > 0 && done >= total) return "positive";
    return late ? "negative" : "accent";
  };

  // Which columns fill this widget's slots, resolved by the host.
  const slots = context.slots ?? {};
  const valueAt = slots.value?.[0];
  const totalAt = slots.total?.[0];
  const labelAt = slots.label?.[0];

  const rows = data.rows ?? [];
  if (!rows.length) return empty(say("noRows"));
  if (valueAt === undefined) return empty(say("noNumeric"));

  const number = (row: Row, index: number): number =>
    typeof row[index] === "number" ? (row[index] as number) : 0;
  const name = (row: Row, fallback: string): string =>
    labelAt !== undefined && row[labelAt] !== null ? String(row[labelAt]) : fallback;

  // With a total column each row is a part of its own whole; without one the
  // rows are parts of each other, which is what a set of counts is.
  const wholeOf = (row: Row): number => {
    if (totalAt !== undefined) return number(row, totalAt) || 1;
    let sum = 0;
    for (const other of rows) sum += number(other, valueAt);
    return sum || 1;
  };

  if (each) {
    return column(
      rows.map((row, index) => {
        const value = number(row, valueAt);
        const whole = wholeOf(row);
        return meter(
          name(row, `${say("row")} ${index + 1}`),
          value,
          0,
          whole,
          `${value} ${say("of")} ${whole}`,
          shareTone(value, whole, false)
        );
      })
    );
  }

  // One bar for everything: the parts summed against the whole they are of.
  let value = 0;
  let whole = 0;
  for (const row of rows) {
    value += number(row, valueAt);
    whole += totalAt !== undefined ? number(row, totalAt) : 0;
  }
  if (totalAt === undefined) whole = value;
  return meter(
    rows.length === 1 ? name(rows[0] as Row, say("total")) : say("total"),
    value,
    0,
    whole || 1,
    `${value} ${say("of")} ${whole || 1}`,
    shareTone(value, whole || 1, false)
  );
};

export const progress: BuiltinWidget = { meta, shape, template };
