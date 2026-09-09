/**
 * What this widget calls itself, in every language it supports.
 *
 * Names and option labels live in the module rather than in the app's locale
 * files: a marketplace widget has to be able to name itself without an app
 * release, and the built-ins get no special treatment. Binding *source* labels
 * stay app-owned — they name our endpoints and are shared by every widget.
 */
const meta = {
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

/**
 * This widget's own output, in every language it speaks.
 *
 * Beside `meta` and for the same reason: a column heading and an empty-state
 * line are the widget's words, and there is no app locale file a marketplace
 * widget could add itself to. The host hands `render` the viewer's language
 * tag; `say` picks from here. Formatting numbers and dates is still the host's
 * job — the sandbox has no locale data and no timezone.
 */
const strings = {
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
 *
 * @param {import("../dataShapes").WidgetData} data
 * @param {import("../dataShapes").WidgetConfig} config
 */
function render(data, config, context) {
  // The viewer's language, and this module's own words in it. An older host
  // that passes no context leaves this at English rather than failing.
  const lang = context?.locale || "en";
  const say = (key) => {
    const entry = strings[key] || {};
    return entry[lang] || entry[lang.split("-")[0]] || entry.en || key;
  };
  const detailed = config.columns === "detailed";
  const wantTotals = config.totals === "on";
  const empty = (message) => ({ v: 1, scene: { kind: "empty", message } });

  const table = (columns, rows) => {
    if (!rows.length) return empty(say("nothingToShow"));
    return { v: 1, scene: { kind: "table", columns: columns, rows: rows } };
  };

  // The one widget that declares no shape: it draws whatever it is given, which
  // is what makes it the fallback when nothing else fits a query.
  const columns = data.columns || [];
  const rows = data.rows || [];
  if (!columns.length || !rows.length) return empty(say("noRows"));

  // "The essentials" is the first handful that fit a half-width tile;
  // "everything" is every column the statement returned.
  const shown = (detailed ? columns : columns.slice(0, 5)).slice(0, 12);
  const columnAt = (index) => columns.indexOf(shown[index]);

  const drawn = shown.map((column, index) => {
    const spec = {
      key: "c" + index,
      label: column.name || say("column") + " " + (index + 1),
      align: column.type === "number" ? "end" : "start",
    };
    if (column.type === "date") spec.format = "date";
    return spec;
  });

  const body = rows.map((row) => {
    const record = {};
    for (let index = 0; index < drawn.length; index++) {
      const value = row[columnAt(index)];
      record[drawn[index].key] = value === undefined ? null : value;
    }
    return record;
  });

  if (wantTotals) {
    const totals = {};
    for (let index = 0; index < drawn.length; index++) {
      if (shown[index].type !== "number") {
        totals[drawn[index].key] = index === 0 ? say("total") : null;
        continue;
      }
      let sum = 0;
      for (const row of rows) {
        const value = row[columnAt(index)];
        if (typeof value === "number") sum += value;
      }
      totals[drawn[index].key] = sum;
    }
    body.push(totals);
  }
  return table(drawn, body);
}
