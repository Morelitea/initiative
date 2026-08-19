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
  options: {
    order: {
      label: {
        en: "Stage order",
        de: "Reihenfolge der Stufen",
        es: "Orden de etapas",
        fr: "Ordre des étapes",
      },
      values: {
        source: {
          en: "As the data comes",
          de: "Wie die Daten kommen",
          es: "Según llegan los datos",
          fr: "Dans l'ordre des données",
        },
        descending: {
          en: "Largest first",
          de: "Größte zuerst",
          es: "Mayor primero",
          fr: "Le plus grand d'abord",
        },
      },
    },
  },
};

/**
 * Built-in: funnel — staged counts, and what falls out between them.
 *
 * Stages are *ordered*, which is why they carry no per-stage color: an ordered
 * scale takes one hue that deepens along the sequence, and the renderer derives
 * that from position. Handing each stage a categorical color would say the
 * stages are unrelated identities, which is the opposite of what a funnel means.
 *
 * The order matters too: a workflow's own sequence is usually the point, so
 * sorting is opt-in rather than the default.
 *
 * @param {import("../dataShapes").WidgetData} data
 * @param {import("../dataShapes").WidgetConfig} config
 */
function render(data, config) {
  const sorted = config.order === "descending";

  const empty = (message) => ({ v: 1, scene: { kind: "empty", message } });

  const funnel = (stages) => {
    if (!stages.length) return empty("Nothing to stage");
    const ordered = sorted ? stages.slice().sort((a, b) => b.value - a.value) : stages;
    return { v: 1, scene: { kind: "funnel", stages: ordered } };
  };

  switch (data.source) {
    case "task_counts": {
      const rows = data.rows || [];
      if (!rows.length) return empty("No tasks match");
      return funnel(rows.map((row) => ({ label: row.bucket, value: row.count })));
    }

    case "sheet_range": {
      const range = data.range;
      if (!range || !range.rows.length) return empty("Range is empty");
      // A label column and a number column: the first of each, so a two-column
      // range reads without configuration.
      const firstRow = range.rows[0];
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
