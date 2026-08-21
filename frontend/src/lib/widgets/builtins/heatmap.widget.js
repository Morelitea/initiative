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
  needDayBucket: {
    en: "Group this binding by day to plot it on a calendar",
    de: "Gruppiere diese Datenquelle nach Tag, um sie im Kalender zu zeigen",
    es: "Agrupa esta fuente por día para verla en un calendario",
    fr: "Groupez cette source par jour pour l'afficher sur un calendrier",
  },
  cannotDraw: {
    en: "This widget cannot draw ",
    de: "Dieses Widget kann das nicht zeichnen: ",
    es: "Este widget no puede dibujar ",
    fr: "Ce widget ne peut pas dessiner ",
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

  switch (data.source) {
    case "task_counts": {
      const rows = data.rows || [];
      // Only a date-bucketed count has a calendar shape; anything else has no
      // day to place, and a made-up placement would be a lie.
      const dated = rows.filter((row) => typeof row.date === "number");
      if (!dated.length) {
        return empty(say("needDayBucket"));
      }
      return grid(dated.map((row) => ({ date: row.date, count: row.count })));
    }

    default:
      return empty(say("cannotDraw") + data.source);
  }
}
