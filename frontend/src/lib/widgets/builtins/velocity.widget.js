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
    en: "Velocity",
    de: "Velocity",
    es: "Velocidad",
    fr: "Vélocité",
  },
  description: {
    en: "Work finished per week, with the latest week held against the one before.",
    de: "Erledigte Arbeit pro Woche, die letzte Woche im Vergleich zur Vorwoche.",
    es: "Trabajo terminado por semana, con la última semana frente a la anterior.",
    fr: "Travail terminé par semaine, la dernière semaine comparée à la précédente.",
  },
  options: {
    mark: {
      label: {
        en: "Style",
        de: "Darstellung",
        es: "Estilo",
        fr: "Style",
      },
      values: {
        bar: {
          en: "Bars",
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
      },
    },
  },
};

/**
 * Built-in: velocity — completions per week.
 *
 * Weeks are anchored on Sundays in UTC, the same grid the heatmap draws, and
 * gaps are filled with zero so a quiet week reads as quiet rather than
 * vanishing. Everything is anchored on the data's own latest week — not on the
 * clock — so the same rows always draw the same picture.
 *
 * @param {import("../dataShapes").WidgetData} data
 * @param {import("../dataShapes").WidgetConfig} config
 */
function render(data, config) {
  const DAY = 86400000;
  const WEEK = 7 * DAY;
  const empty = (message) => ({ v: 1, scene: { kind: "empty", message } });

  switch (data.source) {
    case "tasks": {
      const rows = data.rows || [];
      if (!rows.length) return empty("No tasks match");

      // The Sunday-anchored week each completion lands in.
      const weekOf = (epoch) => {
        const at = new Date(epoch);
        const midnight = Date.UTC(at.getUTCFullYear(), at.getUTCMonth(), at.getUTCDate());
        return midnight - at.getUTCDay() * DAY;
      };

      const byWeek = new Map();
      for (const task of rows) {
        if (task.completedAt === null) continue;
        const week = weekOf(task.completedAt);
        byWeek.set(week, (byWeek.get(week) || 0) + 1);
      }
      if (!byWeek.size) return empty("Nothing finished yet");

      const weeks = [...byWeek.keys()];
      const first = Math.min.apply(null, weeks);
      const last = Math.max.apply(null, weeks);

      const points = [];
      let total = 0;
      for (let week = first; week <= last; week += WEEK) {
        const count = byWeek.get(week) || 0;
        total += count;
        points.push({ x: new Date(week).toISOString().slice(0, 10), y: count });
      }

      const latest = points[points.length - 1].y;
      const previous = points.length > 1 ? points[points.length - 2].y : 0;
      const average = Math.round((total / points.length) * 10) / 10;

      return {
        v: 1,
        scene: {
          kind: "stack",
          direction: "column",
          gap: "sm",
          weights: [1, 2],
          children: [
            {
              kind: "metric",
              value: latest,
              label: "Latest week",
              caption: "avg " + average + " per week",
              // Percent change only means something against a non-zero base.
              delta: previous > 0 ? (latest - previous) / previous : undefined,
              deltaGood: "up",
            },
            {
              kind: "series",
              mark: config.mark || "bar",
              series: [{ name: "Finished", points, tone: "accent" }],
            },
          ],
        },
      };
    }

    default:
      return empty("This widget cannot draw " + data.source);
  }
}
