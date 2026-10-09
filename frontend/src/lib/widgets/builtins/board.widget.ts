/**
 * Built-in: board — tasks dealt into columns.
 *
 * Display only, like every widget on a dashboard: a card is a card, not a
 * handle. There is nothing to drag it onto and no affordance suggesting there
 * is, because moving work between states is a project view's job and a
 * dashboard only ever reads.
 *
 * What a column stands for is this widget's whole decision — a status, the
 * person on the work, a tag, or one of the initiative's own custom properties.
 * That last one is why the property arrives on the *binding* rather than as a
 * display option: options are a closed set of literals fixed at build time, and
 * a team's own field is by definition one this build never heard of. The host
 * resolves the binding to the property's name and the values it can take, so an
 * option nobody has used yet still gets its column instead of quietly ceasing
 * to exist.
 */

import type { CellValue } from "../dataShapes";
import type { BoardCard, BoardColumn, BoardNode } from "../sceneSpec";
import type { WidgetMeta } from "../widgetMeta";
import template from "./board.widget.html?template";
import { type BuiltinWidget, empty, sayer, type WidgetStrings } from "./builtin";

/** What this widget calls itself, in every language it supports. */
const meta: WidgetMeta = {
  name: {
    en: "Board",
    de: "Board",
    es: "Tablero",
    fr: "Tableau",
  },
  description: {
    en: "Tasks dealt into columns — by status, by who is on them, or by one of your own fields.",
    de: "Aufgaben in Spalten — nach Status, nach zuständiger Person oder nach einem eigenen Feld.",
    es: "Tareas repartidas en columnas: por estado, por quién las lleva o por un campo propio.",
    fr: "Les tâches réparties en colonnes : par statut, par personne en charge ou selon l'un de vos champs.",
  },
  options: {
    sort: {
      label: {
        en: "Card order",
        de: "Kartenreihenfolge",
        es: "Orden de tarjetas",
        fr: "Ordre des cartes",
      },
      values: {
        label: { en: "By name", de: "Nach Name", es: "Por nombre", fr: "Par nom" },
        date: { en: "By date", de: "Nach Datum", es: "Por fecha", fr: "Par date" },
      },
    },
    cards: {
      label: {
        en: "Cards show",
        de: "Karten zeigen",
        es: "Las tarjetas muestran",
        fr: "Les cartes montrent",
      },
      values: {
        standard: {
          en: "The essentials",
          de: "Das Wesentliche",
          es: "Lo esencial",
          fr: "L'essentiel",
        },
        compact: { en: "Titles only", de: "Nur Titel", es: "Solo títulos", fr: "Les titres seuls" },
        detailed: {
          en: "Everything the card carries",
          de: "Alles, was die Karte enthält",
          es: "Todo lo que trae la tarjeta",
          fr: "Tout ce que la carte contient",
        },
      },
    },
    highlight: {
      label: { en: "Highlight", de: "Hervorheben", es: "Destacar", fr: "Mettre en avant" },
      values: {
        overdue: {
          en: "Anything overdue",
          de: "Alles Überfällige",
          es: "Todo lo vencido",
          fr: "Tout ce qui est en retard",
        },
        off: { en: "Nothing", de: "Nichts", es: "Nada", fr: "Rien" },
      },
    },
    columns: {
      label: {
        en: "Column order",
        de: "Spaltenreihenfolge",
        es: "Orden de las columnas",
        fr: "Ordre des colonnes",
      },
      values: {
        natural: {
          en: "The field's own",
          de: "Die des Feldes",
          es: "El del propio campo",
          fr: "Celui du champ",
        },
        largest: {
          en: "Fullest first",
          de: "Vollste zuerst",
          es: "Las más llenas primero",
          fr: "Les plus remplies d'abord",
        },
        label: { en: "By name", de: "Nach Name", es: "Por nombre", fr: "Par nom" },
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
  needColumns: {
    en: "Needs a card column and a column to group by",
    de: "Benötigt eine Karten- und eine Gruppierungsspalte",
    es: "Necesita una columna de tarjeta y otra por la que agrupar",
    fr: "Nécessite une colonne de carte et une colonne de regroupement",
  },
  noValue: { en: "No", de: "Ohne", es: "Sin", fr: "Sans" },
  untitled: { en: "Untitled", de: "Ohne Titel", es: "Sin título", fr: "Sans titre" },
  late: { en: "late", de: "überfällig", es: "atrasadas", fr: "en retard" },
};

type Row = CellValue[];

/** One column while the rows are dealt: its raw value, its rows, and the order
 *  the statement first produced it in. */
interface Bucket {
  key: string | null;
  rows: Row[];
  rank: number;
}

const shape: BuiltinWidget["shape"] = (data, config, context) => {
  const say = sayer(strings, context.locale);

  // Which columns fill this widget's slots, resolved by the host. What a board
  // groups by is therefore the author's mapping rather than a display option:
  // the column column *is* the grouping.
  const slots = context.slots ?? {};
  const cardAt = slots.card?.[0];
  const columnAt = slots.column?.[0];
  const dateAt = slots.date?.[0];

  const rows = data.rows ?? [];
  const columnsMeta = data.columns ?? [];
  const detail = config.cards || "standard";
  const sort = config.sort || "label";
  const markOverdue = config.highlight !== "off";
  const columnOrder = config.columns || "natural";

  if (!rows.length) return empty(say("noRows"));
  if (cardAt === undefined || columnAt === undefined) return empty(say("needColumns"));

  // The clock the host handed us. A widget must never invent one.
  const today = context.now ?? Date.now();

  const text = (row: Row, index: number | undefined): string | null =>
    index !== undefined && row[index] !== null && row[index] !== undefined
      ? String(row[index])
      : null;

  const dateOf = (row: Row): number | undefined => {
    if (dateAt === undefined) return undefined;
    const value = row[dateAt];
    return typeof value === "number" ? value : undefined;
  };

  const isOverdue = (row: Row): boolean => {
    const date = dateOf(row);
    return date !== undefined && date < today;
  };

  // --- the columns --------------------------------------------------------
  //
  // Keyed on the raw value, so two values that happen to read alike stay two
  // columns. The empty bucket is named for the column it is missing from.
  const columns = new Map<string, Bucket>();
  const columnFor = (key: string | null): Bucket => {
    const id = key === null ? " none" : key;
    let column = columns.get(id);
    if (!column) {
      column = { key, rows: [], rank: columns.size };
      columns.set(id, column);
    }
    return column;
  };
  for (const row of rows) columnFor(text(row, columnAt));

  const emptyLabel = columnsMeta[columnAt]
    ? `${say("noValue")} ${columnsMeta[columnAt].name}`
    : say("noValue");

  // --- cards --------------------------------------------------------------
  //
  // Chips are every other column the statement returned, which is what makes a
  // card show more without the widget knowing what a task is. The card's own
  // column and the one it is grouped by are never repeated on it.
  const chipColumns = columnsMeta
    .map((_column, index) => index)
    .filter((index) => index !== cardAt && index !== columnAt && index !== dateAt);

  const cardFor = (row: Row): BoardCard => {
    const card: BoardCard = { title: text(row, cardAt) || say("untitled") };
    if (markOverdue && isOverdue(row)) card.tone = "negative";
    if (detail === "compact") return card;

    const limit = detail === "detailed" ? chipColumns.length : 2;
    const chips: string[] = [];
    for (const index of chipColumns.slice(0, limit)) {
      const value = text(row, index);
      if (value !== null) chips.push(value);
    }
    if (chips.length) card.chips = chips;
    const date = dateOf(row);
    if (date !== undefined) card.date = date;
    return card;
  };

  // --- order --------------------------------------------------------------

  const compare = (a: Row, b: Row): number => {
    if (sort === "date" && dateAt !== undefined) {
      // Undated work has no place on a date ladder, so it sits at the foot
      // rather than being given a date it does not have.
      const left = dateOf(a) ?? Infinity;
      const right = dateOf(b) ?? Infinity;
      if (left !== right) return left - right;
    }
    const leftTitle = text(a, cardAt) || "";
    const rightTitle = text(b, cardAt) || "";
    return leftTitle < rightTitle ? -1 : leftTitle > rightTitle ? 1 : 0;
  };

  const labelled = [...columns.values()].map((column) => ({
    column,
    label: column.key === null ? emptyLabel : column.key,
  }));

  const byLabel = (a: { label: string }, b: { label: string }): number =>
    a.label < b.label ? -1 : a.label > b.label ? 1 : 0;

  for (const row of rows) {
    const key = text(row, columnAt);
    columnFor(key).rows.push(row);
  }

  if (columnOrder === "largest") {
    labelled.sort((a, b) => b.column.rows.length - a.column.rows.length);
  } else if (columnOrder === "label") {
    labelled.sort(byLabel);
  } else {
    // The order the statement produced them in, with the empty bucket last —
    // an ORDER BY is the author saying what the order should be.
    labelled.sort((a, b) => {
      if ((a.column.key === null) !== (b.column.key === null)) {
        return a.column.key === null ? 1 : -1;
      }
      return a.column.rank - b.column.rank;
    });
  }

  const scene: BoardNode = { kind: "board", columns: [] };
  for (const entry of labelled) {
    const ordered = entry.column.rows.slice().sort(compare);
    const column: BoardColumn = { label: entry.label, cards: ordered.map(cardFor) };
    if (markOverdue) {
      let late = 0;
      for (const row of ordered) if (isOverdue(row)) late++;
      if (late) column.caption = `${late} ${say("late")}`;
    }
    scene.columns.push(column);
  }
  return scene;
};

export const board: BuiltinWidget = { meta, shape, template };
