/**
 * Built-in: table — a read-only grid over whatever the binding returns.
 *
 * Display only, and pointedly so: no row actions, no inline editing, no
 * check-off. Working with tasks is a project view's job — this shows what is
 * there and nothing more.
 *
 * A statement decides the columns, so "the essentials" is the first handful
 * that fit a half-width tile and "everything" is all of them. Alignment and
 * date formatting come from each column's declared type rather than from
 * sniffing the first row, so a column of nulls still reads as what it is.
 */

import type { TableCell, TableColumn, TableNode } from "../sceneSpec";
import type { WidgetMeta } from "../widgetMeta";
import { type BuiltinWidget, empty, sayer, type WidgetStrings } from "./builtin";
import template from "./table.widget.html?template";

/** What this widget calls itself, in every language it supports. */
const meta: WidgetMeta = {
  name: {
    en: "Table",
    de: "Tabelle",
    es: "Tabla",
    fr: "Tableau",
  },
  description: {
    en: "A plain read-only grid of rows and columns.",
    de: "Ein einfaches, schreibgeschütztes Raster aus Zeilen und Spalten.",
    es: "Una cuadrícula sencilla de solo lectura con filas y columnas.",
    fr: "Une simple grille en lecture seule, en lignes et colonnes.",
  },
  options: {
    columns: {
      label: {
        en: "Columns",
        de: "Spalten",
        es: "Columnas",
        fr: "Colonnes",
      },
      values: {
        standard: {
          en: "The essentials",
          de: "Das Wesentliche",
          es: "Lo esencial",
          fr: "L'essentiel",
        },
        detailed: {
          en: "Everything the row carries",
          de: "Alles, was die Zeile enthält",
          es: "Todo lo que trae la fila",
          fr: "Tout ce que la ligne contient",
        },
      },
    },
    totals: {
      label: {
        en: "Totals row",
        de: "Summenzeile",
        es: "Fila de totales",
        fr: "Ligne de totaux",
      },
      values: {
        off: { en: "Hide", de: "Ausblenden", es: "Ocultar", fr: "Masquer" },
        on: { en: "Show", de: "Anzeigen", es: "Mostrar", fr: "Afficher" },
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
  nothingToShow: {
    en: "Nothing to show",
    de: "Nichts anzuzeigen",
    es: "Nada que mostrar",
    fr: "Rien à afficher",
  },
  total: { en: "Total", de: "Gesamt", es: "Total", fr: "Total" },
  column: { en: "Column", de: "Spalte", es: "Columna", fr: "Colonne" },
};

const shape: BuiltinWidget["shape"] = (data, config, context) => {
  const say = sayer(strings, context.locale);
  const detailed = config.columns === "detailed";
  const wantTotals = config.totals === "on";

  // The one widget that declares no shape: it draws whatever it is given, which
  // is what makes it the fallback when nothing else fits a query.
  const columns = data.columns ?? [];
  const rows = data.rows ?? [];
  if (!columns.length || !rows.length) return empty(say("noRows"));

  // "The essentials" is the first handful that fit a half-width tile;
  // "everything" is every column the statement returned. Either way the drawn
  // columns are the leading ones, so a drawn column's index is its data index.
  const shown = (detailed ? columns : columns.slice(0, 5)).slice(0, 12);

  const drawn = shown.map((column, index) => {
    const spec: TableColumn = {
      key: `c${index}`,
      label: column.name || `${say("column")} ${index + 1}`,
      align: column.type === "number" ? "end" : "start",
    };
    if (column.type === "date") spec.format = "date";
    return spec;
  });

  const body = rows.map((row) => {
    const record: Record<string, TableCell> = {};
    for (const [index, column] of drawn.entries()) {
      const value = row[index];
      record[column.key] = value === undefined ? null : value;
    }
    return record;
  });

  if (wantTotals) {
    const totals: Record<string, TableCell> = {};
    for (const [index, column] of drawn.entries()) {
      if (shown[index]?.type !== "number") {
        totals[column.key] = index === 0 ? say("total") : null;
        continue;
      }
      let sum = 0;
      for (const row of rows) {
        const value = row[index];
        if (typeof value === "number") sum += value;
      }
      totals[column.key] = sum;
    }
    body.push(totals);
  }

  if (!body.length) return empty(say("nothingToShow"));
  return { kind: "table", columns: drawn, rows: body } satisfies TableNode;
};

export const table: BuiltinWidget = { meta, shape, template };
