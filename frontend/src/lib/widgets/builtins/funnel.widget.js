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
    en: "No numeric column to stage",
    de: "Keine Zahlenspalte für Stufen",
    es: "Ninguna columna numérica para las etapas",
    fr: "Aucune colonne numérique à mettre en étapes",
  },
  nothingToStage: {
    en: "Nothing to stage",
    de: "Keine Stufen vorhanden",
    es: "Ninguna etapa",
    fr: "Aucune étape",
  },
  stage: { en: "Stage", de: "Stufe", es: "Etapa", fr: "Étape" },
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
 * @param {import("../dataShapes").TabularData} data
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
  // Which columns fill this widget's slots. Resolved by the host, which is the
  // only place that has the widget's declared shape and the author's overrides
  // together; what arrives is the answer.
  const slots = context?.slots || {};
  const labelAt = (slots.label || [])[0];
  const valueAt = (slots.value || [])[0];
  const sorted = config.order === "descending";

  const empty = (message) => ({ v: 1, scene: { kind: "empty", message } });

  const funnel = (stages) => {
    if (!stages.length) return empty(say("nothingToStage"));
    const ordered = sorted ? stages.slice().sort((a, b) => b.value - a.value) : stages;
    return { v: 1, scene: { kind: "funnel", stages: ordered } };
  };

  const rows = data.rows || [];
  if (!rows.length) return empty(say("noRows"));
  if (valueAt === undefined) return empty(say("noNumeric"));

  return funnel(
    rows.map((row, index) => ({
      label:
        labelAt !== undefined && row[labelAt] !== null
          ? String(row[labelAt])
          : say("stage") + " " + (index + 1),
      value: typeof row[valueAt] === "number" ? row[valueAt] : 0,
    }))
  );
}
