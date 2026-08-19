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
  noTasks: {
    en: "No tasks match",
    de: "Keine Aufgaben passen",
    es: "Ninguna tarea coincide",
    fr: "Aucune tâche ne correspond",
  },
  noCounter: {
    en: "No counter selected",
    de: "Kein Zähler ausgewählt",
    es: "Ningún contador seleccionado",
    fr: "Aucun compteur sélectionné",
  },
  rangeEmpty: {
    en: "Range is empty",
    de: "Bereich ist leer",
    es: "El rango está vacío",
    fr: "La plage est vide",
  },
  noNumeric: {
    en: "No numeric values in range",
    de: "Keine Zahlenwerte im Bereich",
    es: "No hay valores numéricos en el rango",
    fr: "Aucune valeur numérique dans la plage",
  },
  cannotDraw: {
    en: "This widget cannot draw ",
    de: "Dieses Widget kann das nicht zeichnen: ",
    es: "Este widget no puede dibujar ",
    fr: "Ce widget ne peut pas dessiner ",
  },
  total: { en: "Total", de: "Gesamt", es: "Total", fr: "Total" },
  of: { en: "of", de: "von", es: "de", fr: "sur" },
  days: { en: "days", de: "Tage", es: "días", fr: "jours" },
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
  const lang = (context && context.locale) || "en";
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

  switch (data.source) {
    case "counter": {
      const counter = data.counter;
      if (!counter) return empty(say("noCounter"));
      const caption =
        counter.max !== null && counter.max !== undefined
          ? say("of") + " " + counter.max + (counter.unit ? " " + counter.unit : "")
          : counter.unit || undefined;
      // A counter is a current value with no history, so there is nothing
      // honest to draw a trend from.
      return scene(metric(counter.value, counter.name, caption));
    }

    case "task_counts": {
      const rows = data.rows || [];
      if (!rows.length) return empty(say("noTasks"));

      const total = rows.reduce((sum, row) => sum + row.count, 0);
      const dated = rows.filter((row) => typeof row.date === "number");

      // A day-bucketed binding is a time series: report the total, say how it
      // moved, and draw the shape underneath.
      if (dated.length) {
        const ordered = dated.slice().sort((a, b) => a.date - b.date);
        const change = changeOver(ordered.map((row) => row.count));
        const node = metric(
          total,
          undefined,
          ordered.length + " " + say("days"),
          change === null ? undefined : { delta: change, deltaGood: deltaGood }
        );
        return withSparkline(
          node,
          ordered.map((row) => ({ x: row.bucket, y: row.count }))
        );
      }

      if (pick === "largest") {
        let best = rows[0];
        for (const row of rows) if (row.count > best.count) best = row;
        return scene(metric(best.count, best.bucket, say("of") + " " + total));
      }
      if (pick === "first") {
        return scene(metric(rows[0].count, rows[0].bucket, say("of") + " " + total));
      }
      return scene(metric(total, say("total")));
    }

    case "sheet_range": {
      const range = data.range;
      if (!range || !range.rows.length) return empty(say("rangeEmpty"));
      // Sum the first column that holds numbers, so a range like A1:B6 reads
      // as its values rather than its headers.
      const columnIndex = range.rows[0].findIndex((cell) => typeof cell === "number");
      if (columnIndex < 0) return empty(say("noNumeric"));
      const values = [];
      for (const row of range.rows) {
        if (typeof row[columnIndex] === "number") values.push(row[columnIndex]);
      }
      const total = values.reduce((sum, value) => sum + value, 0);
      const change = changeOver(values);
      const node = metric(
        pick === "largest" ? Math.max.apply(null, values) : total,
        range.columns[columnIndex] || undefined,
        undefined,
        change === null ? undefined : { delta: change, deltaGood: deltaGood }
      );
      return withSparkline(
        node,
        values.map((value, index) => ({ x: index + 1, y: value }))
      );
    }

    default:
      return empty(say("cannotDraw") + data.source);
  }
}
