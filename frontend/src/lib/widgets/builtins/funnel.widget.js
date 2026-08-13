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
    en: "Funnel",
    de: "Trichter",
    es: "Embudo",
    fr: "Entonnoir",
  },
  description: {
    en: "Staged counts from widest to narrowest, with the conversion between each stage.",
    de: "Stufenwerte vom breitesten zum schmalsten, mit der Konversion zwischen den Stufen.",
    es: "Recuentos por etapa, de la más amplia a la más estrecha, con la conversión entre cada una.",
    fr: "Des effectifs par étape, du plus large au plus étroit, avec la conversion entre chaque étape.",
  },
};

/**
 * Built-in: funnel — staged counts, widest first.
 *
 * @param {import("../dataShapes").WidgetData} data
 * @param {import("../dataShapes").WidgetConfig} config
 */
function render(data, config) {
  const empty = (message) => ({ v: 1, scene: { kind: "empty", message } });

  const funnel = (stages) => {
    if (!stages.length) return empty("No stages to show");
    // A funnel is read top-down as narrowing, so the widest stage leads
    // regardless of the order the source happened to return.
    const ordered = [...stages].sort((a, b) => b.value - a.value);
    return {
      v: 1,
      scene: {
        kind: "funnel",
        stages: ordered,
        format: config.format || undefined,
      },
    };
  };

  switch (data.source) {
    case "task_counts": {
      const rows = data.rows || [];
      if (!rows.length) return empty("No tasks match");
      return funnel(rows.map((row) => ({ label: row.bucket, value: row.count })));
    }

    case "sheet_range": {
      const range = data.range;
      if (!range?.rows.length) return empty("Range is empty");
      const [firstRow] = range.rows;
      const labelIndex = firstRow.findIndex((cell) => typeof cell !== "number");
      const valueIndex = firstRow.findIndex((cell) => typeof cell === "number");
      if (valueIndex < 0) return empty("No numeric values in range");
      return funnel(
        range.rows.map((row, index) => ({
          label:
            labelIndex >= 0 && row[labelIndex] !== null
              ? String(row[labelIndex])
              : "Stage " + (index + 1),
          value: typeof row[valueIndex] === "number" ? row[valueIndex] : 0,
        }))
      );
    }

    default:
      return empty("This widget cannot draw " + data.source);
  }
}
