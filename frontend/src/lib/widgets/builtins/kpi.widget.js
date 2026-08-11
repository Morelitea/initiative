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
    en: "KPI",
    de: "KPI",
    es: "KPI",
    fr: "Indicateur clé",
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
  },
};

/**
 * Built-in: KPI — one big number.
 *
 * Like every built-in, this is an ordinary widget module: it runs in the same
 * sandbox as an installed listing's widget, with the same capabilities (none)
 * and the same contract. Being in this repo buys it review, not privilege.
 *
 * @param {import("../dataShapes").WidgetData} data
 * @param {import("../dataShapes").WidgetConfig} config
 */
function render(data, config) {
  const format = config.format || "plain";

  const metric = (value, label, caption) => ({
    v: 1,
    scene: {
      kind: "metric",
      value: Number.isFinite(value) ? value : 0,
      label: label || undefined,
      caption: caption || undefined,
      format,
    },
  });

  const empty = (message) => ({ v: 1, scene: { kind: "empty", message } });

  switch (data.source) {
    case "counter": {
      const counter = data.counter;
      if (!counter) return empty("No counter selected");
      const caption =
        counter.max !== null && counter.max !== undefined
          ? "of " + counter.max + (counter.unit ? " " + counter.unit : "")
          : counter.unit || undefined;
      return metric(counter.value, counter.name, caption);
    }

    case "task_counts": {
      const rows = data.rows || [];
      if (!rows.length) return empty("No tasks match");
      // A named bucket reads as that bucket's count; otherwise the total.
      const bucket = config.bucket;
      if (bucket) {
        const match = rows.find((row) => row.bucket === bucket);
        return metric(match ? match.count : 0, bucket);
      }
      const total = rows.reduce((sum, row) => sum + row.count, 0);
      return metric(total, "Total");
    }

    case "my_stats": {
      const days = data.days || [];
      if (!days.length) return empty("Nothing recorded yet");
      return metric(data.total || 0, "Total", days.length + " days");
    }

    case "sheet_range": {
      const range = data.range;
      if (!range?.rows.length) return empty("Range is empty");
      // Sum the first column that holds numbers, so a range like A1:B6 reads
      // as its values rather than its headers.
      const columnIndex = range.rows[0].findIndex((cell) => typeof cell === "number");
      if (columnIndex < 0) return empty("No numeric values in range");
      const total = range.rows.reduce((sum, row) => {
        const cell = row[columnIndex];
        return typeof cell === "number" ? sum + cell : sum;
      }, 0);
      return metric(total, range.columns[columnIndex] || undefined);
    }

    default:
      return empty("This widget cannot draw " + data.source);
  }
}
