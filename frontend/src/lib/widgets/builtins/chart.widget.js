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

/**
 * Built-in: chart — a series drawn as bars, lines, an area, or slices.
 *
 * The workhorse: the `bar_chart`/`line_chart`/`area_chart`/`pie_chart`/
 * `stacked_bar_chart` presets are all this module with a fixed `mark`.
 *
 * What it grew: an order, a category ceiling, a direction, selective value
 * labels, and emphasis. The ceiling is the one worth explaining — past its slot
 * count a categorical palette has no more distinguishable colors, so a chart
 * with thirty projects on it cannot be read however it is drawn. Folding the
 * tail into one "Other" is the honest answer; inventing a thirtieth color is
 * not.
 *
 * @param {import("../dataShapes").WidgetData} data
 * @param {import("../dataShapes").WidgetConfig} config
 */
function render(data, config) {
  const mark = config.mark || "bar";
  const stacked = config.stacked === "true";
  const sort = config.sort || "source";
  const limit = config.limit === "all" || !config.limit ? 0 : Number(config.limit) || 0;
  const horizontal = config.orientation === "bars";
  const labels = config.values && config.values !== "none" ? config.values : undefined;
  const emphasis = config.emphasis || "none";

  const empty = (message) => ({ v: 1, scene: { kind: "empty", message } });

  /** Which series gets to keep its color when the rest go gray. */
  const emphasisIndex = (series) => {
    if (emphasis === "none" || series.length < 2) return undefined;
    if (emphasis === "last") return series.length - 1;
    let best = 0;
    let bestTotal = -Infinity;
    for (let index = 0; index < series.length; index++) {
      let total = 0;
      for (const point of series[index].points) total += point.y;
      if (total > bestTotal) {
        bestTotal = total;
        best = index;
      }
    }
    return best;
  };

  const chart = (series, xLabel, yLabel) => {
    const scene = {
      kind: "series",
      mark: mark,
      series: series,
      stacked: stacked || undefined,
      xLabel: xLabel || undefined,
      yLabel: yLabel || undefined,
      // A legend earns its space only once there is more than one series.
      showLegend: series.length > 1,
      labels: labels,
      horizontal: horizontal && mark === "bar" ? true : undefined,
      emphasis: emphasisIndex(series),
    };
    return { v: 1, scene: scene };
  };

  /**
   * Order the points, then cap how many categories are drawn.
   *
   * Pie slices always read as a share of a whole, so the largest belongs first
   * whatever the chosen order says; everything else keeps the order asked for,
   * and "source" is meaningful more often than not (a day sequence, a workflow
   * order).
   */
  const arrange = (points) => {
    let ordered = points;
    if (sort === "value_desc" || mark === "pie") {
      ordered = points.slice().sort((a, b) => b.y - a.y);
    } else if (sort === "value_asc") {
      ordered = points.slice().sort((a, b) => a.y - b.y);
    } else if (sort === "label") {
      ordered = points.slice().sort((a, b) => String(a.x).localeCompare(String(b.x)));
    }

    if (!limit || ordered.length <= limit) return ordered;
    // The tail becomes one entry rather than more colors. Ordered by value
    // first, so "Other" is genuinely the small remainder.
    const byValue = ordered.slice().sort((a, b) => b.y - a.y);
    const kept = byValue.slice(0, limit);
    let rest = 0;
    for (let index = limit; index < byValue.length; index++) rest += byValue[index].y;
    const keptKeys = {};
    for (const point of kept) keptKeys[String(point.x)] = true;
    const inOrder = ordered.filter((point) => keptKeys[String(point.x)]);
    inOrder.push({ x: "Other", y: rest });
    return inOrder;
  };

  switch (data.source) {
    case "task_counts": {
      const rows = data.rows || [];
      if (!rows.length) return empty("No tasks match");
      return chart([
        {
          name: "Tasks",
          points: arrange(rows.map((row) => ({ x: row.bucket, y: row.count }))),
        },
      ]);
    }

    case "counter_group": {
      const counters = data.counters || [];
      if (!counters.length) return empty("No counters in this group");
      return chart(
        [
          {
            name: data.name || "Counters",
            points: arrange(counters.map((counter) => ({ x: counter.name, y: counter.value }))),
          },
        ],
        undefined,
        counters[0].unit || undefined
      );
    }

    case "projects": {
      const rows = data.rows || [];
      if (!rows.length) return empty("No projects match");
      // Done against outstanding reads as a stack; separately it reads as two
      // comparable series. Either way the same two series serve — and they are
      // ordered together, so the two halves of a bar stay on the same project.
      const done = arrange(rows.map((row) => ({ x: row.name, y: row.doneCount })));
      const order = {};
      done.forEach((point, index) => {
        order[String(point.x)] = index;
      });
      const remaining = rows
        .map((row) => ({ x: row.name, y: Math.max(0, row.taskCount - row.doneCount) }))
        .filter((point) => order[String(point.x)] !== undefined)
        .sort((a, b) => order[String(a.x)] - order[String(b.x)]);

      return chart([
        { name: "Done", points: done, tone: "positive" },
        { name: "Remaining", points: remaining, tone: "muted" },
      ]);
    }

    case "sheet_range": {
      const range = data.range;
      if (!range || !range.rows.length) return empty("Range is empty");
      const firstRow = range.rows[0];
      // First non-numeric column labels the axis; every numeric column becomes
      // a series. A range with no labels falls back to row ordinals.
      const labelIndex = firstRow.findIndex((cell) => typeof cell !== "number");
      const valueIndexes = [];
      firstRow.forEach((cell, index) => {
        if (typeof cell === "number") valueIndexes.push(index);
      });
      if (!valueIndexes.length) return empty("No numeric values in range");

      const series = valueIndexes.slice(0, 12).map((index) => ({
        name: range.columns[index] || "Series " + (index + 1),
        points: arrange(
          range.rows.map((row, rowIndex) => ({
            x: labelIndex >= 0 && row[labelIndex] !== null ? String(row[labelIndex]) : rowIndex + 1,
            y: typeof row[index] === "number" ? row[index] : 0,
          }))
        ),
      }));
      return chart(series, labelIndex >= 0 ? range.columns[labelIndex] : undefined);
    }

    default:
      return empty("This widget cannot draw " + data.source);
  }
}
