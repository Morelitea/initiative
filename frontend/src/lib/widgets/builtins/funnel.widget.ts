/**
 * Built-in: funnel — staged counts, and what falls out between them.
 *
 * Stages are *ordered*, which is why they carry no per-stage colour: an ordered
 * scale takes one hue that deepens along the sequence, and the element derives
 * that from position. Handing each stage a categorical colour would say the
 * stages are unrelated identities, which is the opposite of what a funnel means.
 *
 * The order matters too: a workflow's own sequence is usually the point, so
 * sorting is opt-in rather than the default.
 */

import type { FunnelNode } from "../sceneSpec";
import type { WidgetMeta } from "../widgetMeta";
import { type BuiltinWidget, empty, sayer, type WidgetStrings } from "./builtin";
import template from "./funnel.widget.html?template";

/** What this widget calls itself, in every language it supports. */
const meta: WidgetMeta = {
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

/** This widget's own words, in every language it speaks. */
const strings: WidgetStrings = {
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

const shape: BuiltinWidget["shape"] = (data, config, context) => {
  const say = sayer(strings, context.locale);
  const slots = context.slots ?? {};
  const labelAt = slots.label?.[0];
  const valueAt = slots.value?.[0];

  const rows = data.rows ?? [];
  if (!rows.length) return empty(say("noRows"));
  if (valueAt === undefined) return empty(say("noNumeric"));

  const stages: FunnelNode["stages"] = rows.map((row, index) => ({
    label:
      labelAt !== undefined && row[labelAt] !== null
        ? String(row[labelAt])
        : `${say("stage")} ${index + 1}`,
    value: typeof row[valueAt] === "number" ? (row[valueAt] as number) : 0,
  }));
  if (!stages.length) return empty(say("nothingToStage"));
  const ordered =
    config.order === "descending" ? stages.slice().sort((a, b) => b.value - a.value) : stages;
  return { kind: "funnel", stages: ordered } satisfies FunnelNode;
};

export const funnel: BuiltinWidget = { meta, shape, template };
