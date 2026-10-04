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
    en: "Heatmap",
    de: "Heatmap",
    es: "Mapa de calor",
    fr: "Carte thermique",
  },
  description: {
    en: "Daily activity as a calendar grid, one column per week.",
    de: "Tägliche Aktivität als Kalenderraster, eine Spalte pro Woche.",
    es: "La actividad diaria como una cuadrícula de calendario, una columna por semana.",
    fr: "L'activité quotidienne sous forme de grille calendaire, une colonne par semaine.",
  },
  options: {
    tone: {
      label: { en: "Colour", de: "Farbe", es: "Color", fr: "Couleur" },
      values: {
        accent: { en: "Accent", de: "Akzent", es: "Acento", fr: "Accent" },
        positive: { en: "Green", de: "Grün", es: "Verde", fr: "Vert" },
        warning: { en: "Amber", de: "Bernstein", es: "Ámbar", fr: "Ambre" },
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
  nothingRecorded: {
    en: "Nothing recorded yet",
    de: "Noch nichts erfasst",
    es: "Aún no hay registros",
    fr: "Rien d'enregistré pour l'instant",
  },
  needDayColumn: {
    en: "No date column to place values on",
    de: "Keine Datumsspalte für die Werte",
    es: "Ninguna columna de fecha donde situar los valores",
    fr: "Aucune colonne de date où placer les valeurs",
  },
  months: {
    Jan: { en: "Jan", de: "Jan", es: "Ene", fr: "Janv" },
    Feb: { en: "Feb", de: "Feb", es: "Feb", fr: "Févr" },
    Mar: { en: "Mar", de: "Mär", es: "Mar", fr: "Mars" },
    Apr: { en: "Apr", de: "Apr", es: "Abr", fr: "Avr" },
    May: { en: "May", de: "Mai", es: "May", fr: "Mai" },
    Jun: { en: "Jun", de: "Jun", es: "Jun", fr: "Juin" },
    Jul: { en: "Jul", de: "Jul", es: "Jul", fr: "Juil" },
    Aug: { en: "Aug", de: "Aug", es: "Ago", fr: "Août" },
    Sep: { en: "Sep", de: "Sep", es: "Sep", fr: "Sept" },
    Oct: { en: "Oct", de: "Okt", es: "Oct", fr: "Oct" },
    Nov: { en: "Nov", de: "Nov", es: "Nov", fr: "Nov" },
    Dec: { en: "Dec", de: "Dez", es: "Dic", fr: "Déc" },
  },
  week: { en: "Weeks", de: "Wochen", es: "Semanas", fr: "Semaines" },
  weekdays: {
    Sun: { en: "Sun", de: "So", es: "Dom", fr: "Dim" },
    Mon: { en: "Mon", de: "Mo", es: "Lun", fr: "Lun" },
    Tue: { en: "Tue", de: "Di", es: "Mar", fr: "Mar" },
    Wed: { en: "Wed", de: "Mi", es: "Mié", fr: "Mer" },
    Thu: { en: "Thu", de: "Do", es: "Jue", fr: "Jeu" },
    Fri: { en: "Fri", de: "Fr", es: "Vie", fr: "Ven" },
    Sat: { en: "Sat", de: "Sa", es: "Sáb", fr: "Sam" },
  },
};

/**
 * Built-in: heatmap — activity density over a calendar grid.
 *
 * Lays days out the way a contribution graph does: one column per week, one row
 * per weekday. All date maths is UTC, because the sandbox has no timezone and
 * the grid only needs to be self-consistent.
 *
 * Which date each task lands on is the *binding's* choice, not this widget's —
 * completion, creation, or due date are three different questions and the
 * widget draws whichever it was handed. What it adds here is the month strip
 * along the top: a column is labelled only where a new month starts, so the
 * grid gets a few anchors instead of a repeated week number nobody reads.
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
  const DAY = 86400000;
  const empty = (message) => ({ v: 1, scene: { kind: "empty", message } });

  /** Weekday and month names in the viewer's language. Short forms, because
   *  the axis strip has room for three or four characters and no more. */
  const pick = (table, key) => {
    const entry = table[key] || {};
    return entry[lang] || entry[lang.split("-")[0]] || entry.en || key;
  };
  const WEEKDAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"].map((key) =>
    pick(strings.weekdays, key)
  );
  const MONTHS = [
    "Jan",
    "Feb",
    "Mar",
    "Apr",
    "May",
    "Jun",
    "Jul",
    "Aug",
    "Sep",
    "Oct",
    "Nov",
    "Dec",
  ].map((key) => pick(strings.months, key));

  /** @param {{date: number, count: number}[]} days */
  const grid = (days) => {
    if (!days.length) return empty(say("nothingRecorded"));

    const sorted = days.slice().sort((a, b) => a.date - b.date);
    // Anchor on the Sunday at or before the first day, so column 0 is a whole
    // week and every later date lands on a stable column.
    const first = new Date(sorted[0].date);
    const anchor =
      Date.UTC(first.getUTCFullYear(), first.getUTCMonth(), first.getUTCDate()) -
      first.getUTCDay() * DAY;

    const cells = [];
    const monthByColumn = {};
    let max = 0;
    let columns = 0;

    for (const day of sorted) {
      const at = new Date(day.date);
      const midnight = Date.UTC(at.getUTCFullYear(), at.getUTCMonth(), at.getUTCDate());
      const offset = Math.floor((midnight - anchor) / DAY);
      if (offset < 0) continue;
      const column = Math.floor(offset / 7);
      if (column + 1 > columns) columns = column + 1;
      if (day.count > max) max = day.count;
      // The first column a month appears in is where its name goes.
      const month = at.getUTCMonth();
      if (monthByColumn[column] === undefined) monthByColumn[column] = month;
      cells.push({
        x: column,
        y: at.getUTCDay(),
        value: day.count,
        label: day.count + " on " + at.toISOString().slice(0, 10),
      });
    }
    if (!cells.length) return empty(say("nothingRecorded"));

    // Label a column only where the month changes; the rest stay empty so the
    // strip reads as a few anchors rather than a wall of text.
    const xLabels = [];
    let previous = -1;
    for (let column = 0; column < columns; column++) {
      const month = monthByColumn[column];
      if (month !== undefined && month !== previous) {
        xLabels.push(MONTHS[month]);
        previous = month;
      } else {
        xLabels.push("");
      }
    }

    return {
      v: 1,
      scene: {
        kind: "matrix",
        cells: cells,
        max: max || 1,
        xLabels: xLabels,
        yLabels: WEEKDAYS,
        tone:
          config.tone === "positive"
            ? "positive"
            : config.tone === "warning"
              ? "warning"
              : "accent",
      },
    };
  };

  const tone =
    config.tone === "positive" ? "positive" : config.tone === "warning" ? "warning" : "accent";

  /**
   * How far apart the dates are. A statement grouped by week, month, quarter
   * or year rounds every date down to the start of one, and drawing those on a
   * day grid would leave one lit cell per week, month or year.
   */
  const grainOf = (days) => {
    const moments = days.map((day) => new Date(day.date));
    if (moments.length < 2) return "day";
    const every = (test) => moments.every(test);
    const midnight = (at) =>
      at.getUTCHours() === 0 && at.getUTCMinutes() === 0 && at.getUTCSeconds() === 0;
    if (!every(midnight)) return "day";
    const first = (at) => at.getUTCDate() === 1;
    if (every((at) => first(at) && at.getUTCMonth() === 0)) return "year";
    if (every((at) => first(at) && at.getUTCMonth() % 3 === 0)) return "quarter";
    if (every(first)) return "month";
    if (every((at) => at.getUTCDay() === 1)) return "week";
    return "day";
  };

  /** One cell per period: months and quarters as a row per year, weeks and
   *  years as one strip. */
  const periods = (days, grain) => {
    const sorted = days.slice().sort((a, b) => a.date - b.date);
    const firstYear = new Date(sorted[0].date).getUTCFullYear();
    const lastYear = new Date(sorted[sorted.length - 1].date).getUTCFullYear();
    const cells = [];
    let max = 0;
    let xLabels = [];
    let yLabels = [""];
    for (const day of sorted) if (day.count > max) max = day.count;

    if (grain === "month" || grain === "quarter") {
      const perYear = grain === "month" ? 12 : 4;
      xLabels = grain === "month" ? MONTHS.slice() : ["Q1", "Q2", "Q3", "Q4"];
      yLabels = [];
      for (let year = firstYear; year <= lastYear; year++) yLabels.push(String(year));
      for (const day of sorted) {
        const at = new Date(day.date);
        const slot = grain === "month" ? at.getUTCMonth() : Math.floor(at.getUTCMonth() / 3);
        cells.push({
          x: slot % perYear,
          y: at.getUTCFullYear() - firstYear,
          value: day.count,
          label: day.count + " in " + xLabels[slot] + " " + at.getUTCFullYear(),
        });
      }
    } else if (grain === "year") {
      for (let year = firstYear; year <= lastYear; year++) xLabels.push(String(year));
      for (const day of sorted) {
        const year = new Date(day.date).getUTCFullYear();
        cells.push({
          x: year - firstYear,
          y: 0,
          value: day.count,
          label: day.count + " in " + year,
        });
      }
    } else {
      // Weeks: one strip, a column per week, months named where they change.
      const anchor = sorted[0].date;
      const columns = Math.floor((sorted[sorted.length - 1].date - anchor) / (7 * DAY)) + 1;
      let previous = -1;
      for (let column = 0; column < columns; column++) {
        const month = new Date(anchor + column * 7 * DAY).getUTCMonth();
        xLabels.push(month !== previous ? MONTHS[month] : "");
        previous = month;
      }
      yLabels = [say("week")];
      for (const day of sorted) {
        const at = new Date(day.date);
        cells.push({
          x: Math.round((day.date - anchor) / (7 * DAY)),
          y: 0,
          value: day.count,
          label: day.count + " in the week of " + at.toISOString().slice(0, 10),
        });
      }
    }
    return {
      v: 1,
      scene: {
        kind: "matrix",
        cells: cells,
        max: max || 1,
        xLabels: xLabels,
        yLabels: yLabels,
        tone: tone,
      },
    };
  };

  // Which columns fill this widget's slots, resolved by the host.
  const slots = context?.slots || {};
  const atColumn = (slots.at || [])[0];
  const valueAt = (slots.value || [])[0];

  const rows = data.rows || [];
  // Only a real date has a calendar shape; anything else has no day to place,
  // and a made-up placement would be a lie.
  if (atColumn === undefined || valueAt === undefined) return empty(say("needDayColumn"));
  // Nothing to draw and nothing wrong: a statement that answered with no rows
  // is a question nobody has done anything about yet, which is a different
  // thing from one this widget cannot read.
  if (!rows.length) return empty(say("nothingRecorded"));
  const dated = rows.filter((row) => typeof row[atColumn] === "number");
  if (!dated.length) return empty(say("needDayColumn"));

  const days = dated.map((row) => ({
    date: row[atColumn],
    count: typeof row[valueAt] === "number" ? row[valueAt] : 0,
  }));
  const grain = grainOf(days);
  return grain === "day" ? grid(days) : periods(days, grain);
}
