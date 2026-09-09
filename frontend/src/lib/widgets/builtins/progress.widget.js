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
    en: "Progress",
    de: "Fortschritt",
    es: "Progreso",
    fr: "Progression",
  },
  description: {
    en: "How far a value has come against its own range.",
    de: "Wie weit ein Wert innerhalb seines Wertebereichs fortgeschritten ist.",
    es: "Cuánto ha avanzado un valor dentro de su propio rango.",
    fr: "La progression d'une valeur au sein de sa propre plage.",
  },
  options: {
    breakdown: {
      label: { en: "Show", de: "Anzeigen", es: "Mostrar", fr: "Afficher" },
      values: {
        total: {
          en: "One bar for everything",
          de: "Ein Balken für alles",
          es: "Una barra para todo",
          fr: "Une barre pour l'ensemble",
        },
        each: {
          en: "A bar for each",
          de: "Ein Balken je Eintrag",
          es: "Una barra por cada uno",
          fr: "Une barre pour chacun",
        },
      },
    },
    format: {
      label: { en: "Format", de: "Format", es: "Formato", fr: "Format" },
      values: {
        percent: {
          en: "Percentage",
          de: "Prozent",
          es: "Porcentaje",
          fr: "Pourcentage",
        },
        plain: {
          en: "Plain number",
          de: "Einfache Zahl",
          es: "Número simple",
          fr: "Nombre simple",
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
    en: "No numeric column to measure",
    de: "Keine Zahlenspalte zum Messen",
    es: "Ninguna columna numérica que medir",
    fr: "Aucune colonne numérique à mesurer",
  },
  row: { en: "Row", de: "Zeile", es: "Fila", fr: "Ligne" },
  total: { en: "Total", de: "Gesamt", es: "Total", fr: "Total" },
  done: { en: "Done", de: "Erledigt", es: "Hecho", fr: "Terminé" },
  of: { en: "of", de: "von", es: "de", fr: "sur" },
};

/**
 * Built-in: progress — a meter, or a column of them.
 *
 * A meter answers "how far along, against what?", which needs both ends of the
 * range stated. A counter brings its own (its min and max); a set of tasks
 * brings a denominator; a project brings both plus, where it has an end date,
 * an idea of where it *should* be by now — drawn as a target mark so the fill
 * reads against the plan rather than against the bar's own end.
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
  const each = config.breakdown === "each";
  const format = config.format === "plain" ? "plain" : "percent";
  const today = Date.now();

  const empty = (message) => ({ v: 1, scene: { kind: "empty", message } });

  const meter = (label, value, min, max, caption, tone, target) => {
    const node = {
      kind: "progress",
      value: value,
      min: min,
      max: max,
      label: label || undefined,
      caption: caption || undefined,
      tone: tone || undefined,
      format: format,
    };
    if (typeof target === "number") node.target = target;
    return node;
  };

  /** Several meters stacked. One is drawn on its own — a stack of one is a
   *  wrapper with nothing to compose. */
  const column = (nodes) => {
    if (!nodes.length) return empty(say("nothingToMeasure"));
    if (nodes.length === 1) return { v: 1, scene: nodes[0] };
    return {
      v: 1,
      scene: { kind: "stack", direction: "column", gap: "sm", children: nodes.slice(0, 12) },
    };
  };

  const shareTone = (done, total, late) => {
    if (total > 0 && done >= total) return "positive";
    return late ? "negative" : "accent";
  };

  // Which columns fill this widget's slots, resolved by the host.
  const slots = context?.slots || {};
  const valueAt = (slots.value || [])[0];
  const totalAt = (slots.total || [])[0];
  const labelAt = (slots.label || [])[0];

  const rows = data.rows || [];
  if (!rows.length) return empty(say("noRows"));
  if (valueAt === undefined) return empty(say("noNumeric"));

  const number = (row, index) => (typeof row[index] === "number" ? row[index] : 0);
  const name = (row, fallback) =>
    labelAt !== undefined && row[labelAt] !== null ? String(row[labelAt]) : fallback;

  // With a total column each row is a part of its own whole; without one the
  // rows are parts of each other, which is what a set of counts is.
  const wholeOf = (row) => {
    if (totalAt !== undefined) return number(row, totalAt) || 1;
    let sum = 0;
    for (const other of rows) sum += number(other, valueAt);
    return sum || 1;
  };

  if (each) {
    return column(
      rows.map((row, index) => {
        const value = number(row, valueAt);
        const whole = wholeOf(row);
        return meter(
          name(row, say("row") + " " + (index + 1)),
          value,
          0,
          whole,
          value + " " + say("of") + " " + whole,
          shareTone(value, whole, false)
        );
      })
    );
  }

  // One bar for everything: the parts summed against the whole they are of.
  let value = 0;
  let whole = 0;
  for (const row of rows) {
    value += number(row, valueAt);
    whole += totalAt !== undefined ? number(row, totalAt) : 0;
  }
  if (totalAt === undefined) whole = value;
  return {
    v: 1,
    scene: meter(
      rows.length === 1 ? name(rows[0], say("total")) : say("total"),
      value,
      0,
      whole || 1,
      value + " " + say("of") + " " + (whole || 1),
      shareTone(value, whole || 1, false)
    ),
  };
}
