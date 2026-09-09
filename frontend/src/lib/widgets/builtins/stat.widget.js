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

/**
 * Built-in: Stat — one big number, and what it is doing.
 *
 * Like every built-in, this is an ordinary widget module: it runs in the same
 * sandbox as an installed listing's widget, with the same capabilities (none)
 * and the same contract. Being in this repo buys it review, not privilege.
 *
 * The trend is why the widget is more than a number in a box. When the binding
 * is bucketed by day, the rows *are* a time series, so the widget splits them
 * into two halves and reports the later against the earlier — which is what
 * anyone reading a dashboard actually wants to know, and what the description
 * has promised since the first release without delivering it.
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
  const format = config.format || "plain";
  const pick = config.pick || "total";
  const wantTrend = config.trend === "on";
  const deltaGood = config.direction === "down_good" ? "down" : "up";

  const empty = (message) => ({ v: 1, scene: { kind: "empty", message } });

  const metric = (value, label, caption, extra) => {
    const node = {
      kind: "metric",
      value: Number.isFinite(value) ? value : 0,
      label: label || undefined,
      caption: caption || undefined,
      format: format,
    };
    if (extra) {
      for (const key in extra) node[key] = extra[key];
    }
    return node;
  };

  const scene = (node) => ({ v: 1, scene: node });

  /** The number above its own history. A `stack` rather than a bespoke node:
   *  the vocabulary already composes, and the sparkline is an ordinary series
   *  the renderer already knows how to draw. */
  const withSparkline = (node, points) => {
    if (!wantTrend || points.length < 3) return scene(node);
    return scene({
      kind: "stack",
      direction: "column",
      gap: "sm",
      // The number leads; the line is context under it.
      weights: [2, 1],
      children: [
        node,
        {
          kind: "series",
          mark: "line",
          showLegend: false,
          series: [{ name: node.label || "", points: points, tone: "accent" }],
        },
      ],
    });
  };

  /** Later half against earlier half, as a fraction. Null when there is not
   *  enough history to make the comparison mean anything — a made-up baseline
   *  would read as a real one. */
  const changeOver = (values) => {
    if (values.length < 4) return null;
    const middle = Math.floor(values.length / 2);
    let earlier = 0;
    let later = 0;
    for (let index = 0; index < middle; index++) earlier += values[index];
    for (let index = middle; index < values.length; index++) later += values[index];
    if (earlier <= 0) return null;
    return (later - earlier) / earlier;
  };

  // Which columns fill this widget's slots, resolved by the host.
  const slots = context?.slots || {};
  const valueAt = (slots.value || [])[0];
  const labelAt = (slots.label || [])[0];

  const rows = data.rows || [];
  if (!rows.length) return empty(say("noRows"));
  if (valueAt === undefined) return empty(say("noNumeric"));

  const number = (row) => (typeof row[valueAt] === "number" ? row[valueAt] : 0);
  const name = (row) =>
    labelAt !== undefined && row[labelAt] !== null ? String(row[labelAt]) : undefined;
  const values = rows.map(number);
  const total = values.reduce((sum, value) => sum + value, 0);
  const heading = data.columns && data.columns[valueAt] ? data.columns[valueAt].name : undefined;

  // A label that orders — a date — makes this a time series: report the total,
  // say how it moved, and draw the shape underneath. A label that does not
  // order has no sequence to read a change from, so none is claimed.
  const overTime =
    labelAt !== undefined && data.columns && data.columns[labelAt]
      ? data.columns[labelAt].type === "date"
      : false;

  if (overTime) {
    const ordered = rows.slice().sort((a, b) => (a[labelAt] || 0) - (b[labelAt] || 0));
    const change = changeOver(ordered.map(number));
    const node = metric(
      total,
      heading,
      ordered.length + " " + say("points"),
      change === null ? undefined : { delta: change, deltaGood: deltaGood }
    );
    return withSparkline(
      node,
      ordered.map((row, index) => ({ x: index + 1, y: number(row) }))
    );
  }

  if (pick === "largest") {
    let best = rows[0];
    for (const row of rows) if (number(row) > number(best)) best = row;
    return scene(metric(number(best), name(best) || heading, say("of") + " " + total));
  }
  if (pick === "first") {
    return scene(metric(number(rows[0]), name(rows[0]) || heading, say("of") + " " + total));
  }
  return scene(metric(total, heading || say("total")));
}
