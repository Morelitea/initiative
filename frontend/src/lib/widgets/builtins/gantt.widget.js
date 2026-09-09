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
    en: "Gantt",
    de: "Gantt",
    es: "Gantt",
    fr: "Gantt",
  },
  description: {
    en: "Scheduled work as bars on a shared timeline, folded into groups you can open.",
    de: "Geplante Arbeit als Balken auf einer gemeinsamen Zeitachse, in aufklappbaren Gruppen.",
    es: "El trabajo programado como barras en una línea de tiempo común, en grupos que puedes desplegar.",
    fr: "Le travail planifié sous forme de barres sur une frise commune, en groupes dépliables.",
  },
  options: {
    scale: {
      label: {
        en: "Time scale",
        de: "Zeitskala",
        es: "Escala de tiempo",
        fr: "Échelle de temps",
      },
      values: {
        day: {
          en: "Days",
          de: "Tage",
          es: "Días",
          fr: "Jours",
        },
        week: {
          en: "Weeks",
          de: "Wochen",
          es: "Semanas",
          fr: "Semaines",
        },
        month: {
          en: "Months",
          de: "Monate",
          es: "Meses",
          fr: "Mois",
        },
        quarter: {
          en: "Quarters",
          de: "Quartale",
          es: "Trimestres",
          fr: "Trimestres",
        },
      },
    },
    group: {
      label: {
        en: "Grouping",
        de: "Gruppierung",
        es: "Agrupación",
        fr: "Regroupement",
      },
      values: {
        on: { en: "Fold into groups", de: "In Gruppen falten", es: "Agrupar", fr: "Regrouper" },
        none: { en: "Flat", de: "Flach", es: "Plano", fr: "À plat" },
      },
    },
    rollup: {
      label: {
        en: "Total row",
        de: "Gesamtzeile",
        es: "Fila de total",
        fr: "Ligne de total",
      },
      values: {
        on: {
          en: "Show",
          de: "Anzeigen",
          es: "Mostrar",
          fr: "Afficher",
        },
        off: {
          en: "Hide",
          de: "Ausblenden",
          es: "Ocultar",
          fr: "Masquer",
        },
      },
    },
    start: {
      label: {
        en: "Groups start",
        de: "Gruppen starten",
        es: "Los grupos empiezan",
        fr: "Les groupes démarrent",
      },
      values: {
        open: {
          en: "Open",
          de: "Aufgeklappt",
          es: "Desplegados",
          fr: "Dépliés",
        },
        folded: {
          en: "Folded",
          de: "Zugeklappt",
          es: "Plegados",
          fr: "Repliés",
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
  needDates: {
    en: "Needs a date column to place work on",
    de: "Benötigt eine Datumsspalte für die Einordnung",
    es: "Necesita una columna de fecha donde situar el trabajo",
    fr: "Nécessite une colonne de date où situer le travail",
  },
  nothingSchedYet: {
    en: "Nothing with a date",
    de: "Nichts mit Datum",
    es: "Nada con fecha",
    fr: "Rien avec une date",
  },
  everything: { en: "Everything", de: "Alles", es: "Todo", fr: "Tout" },
  noGroup: { en: "Ungrouped", de: "Ohne Gruppe", es: "Sin grupo", fr: "Sans groupe" },
  untitled: { en: "Untitled", de: "Ohne Titel", es: "Sin título", fr: "Sans titre" },
};

/**
 * Built-in: Gantt — spans on a time axis, in lanes that fold.
 *
 * The shape it draws is the ordinary one a Gantt has: a work breakdown down the
 * side, bars across a shared axis, a summary bracket over each group that says
 * how much of what is nested under it is finished, diamonds for dated instants
 * that have no duration, and a ghost baseline under work that did not land when
 * it was planned to.
 *
 * Display only, like every widget: bars show when work sits, and nothing here
 * can move a date. Times in and out are epoch milliseconds; how they are
 * labelled is the renderer's decision, since the sandbox has no timezone.
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
  const DAY = 86400000;
  const scale = config.scale || "week";
  const grouping = config.group || "on";
  const wantRollup = config.rollup !== "off";
  const startFolded = config.start === "folded";

  // `Date.now()` is the host's clock, frozen for this render — the sandbox's
  // deterministic shim, not the wall clock. It decides what counts as late, and
  // rides out on the scene so the renderer marks the same instant the widget
  // judged against rather than one of its own.
  const today = Date.now();

  const empty = (message) => ({ v: 1, scene: { kind: "empty", message } });

  const has = (value) => value !== null && value !== undefined;
  const clamp01 = (value) => (value < 0 ? 0 : value > 1 ? 1 : value);
  const share = (done, total) => (total > 0 ? clamp01(done / total) : 0);

  /** The window a lane and everything under it occupies, baselines included —
   *  what a summary bracket has to reach across. */
  const extentOf = (lanes) => {
    let low = null;
    let high = null;
    const widen = (start, end) => {
      if (low === null || start < low) low = start;
      if (high === null || end > high) high = end;
    };
    const visit = (lane) => {
      for (const span of lane.spans) {
        widen(span.start, span.end);
        if (span.baseline) widen(span.baseline.start, span.baseline.end);
      }
      for (const child of lane.children || []) visit(child);
    };
    for (const lane of lanes) visit(lane);
    return low === null ? null : { start: low, end: high };
  };

  const laneStart = (lane) => {
    const extent = extentOf([lane]);
    // Undated lanes sort last rather than to the top, where they would push the
    // dated work down the list.
    return extent ? extent.start : Number.MAX_VALUE;
  };
  const byStart = (a, b) => laneStart(a) - laneStart(b);

  /** A bracket over a set of lanes: it reaches across everything beneath it,
   *  and its fill is how much of that is finished. */
  const summaryLane = (label, children, done, total, tone) => {
    const extent = extentOf(children);
    if (!extent) return null;
    return {
      label: label,
      caption: done + "/" + total,
      tone: tone,
      collapsed: startFolded,
      children: children,
      spans: [
        {
          kind: "summary",
          label: label,
          start: extent.start,
          end: extent.end,
          progress: share(done, total),
          tone: tone,
        },
      ],
    };
  };

  const groupTone = (done, total, late) => {
    if (total > 0 && done >= total) return "positive";
    return late ? "negative" : "accent";
  };

  // Which columns fill this widget's slots, resolved by the host.
  const slots = context?.slots || {};
  const labelAt = (slots.label || [])[0];
  const startAt = (slots.start || [])[0];
  const endAt = (slots.end || [])[0];
  const groupAt = (slots.group || [])[0];

  const at = (row, index) => (index !== undefined ? row[index] : null);
  const moment = (row, index) => {
    const value = at(row, index);
    return typeof value === "number" ? value : null;
  };
  const text = (row, index) => {
    const value = at(row, index);
    return value === null || value === undefined ? null : String(value);
  };

  /** Work whose end has passed reads as behind; there is no completion column
   *  in the general case, so nothing claims one. */
  const isPast = (row) => {
    const end = moment(row, endAt);
    return end !== null && end < today;
  };

  /** One row as its own lane. Returns null for a row with no start — it has
   *  nowhere to sit on an axis, and a zero-width bar at an arbitrary point
   *  would be a lie rather than a gap. */
  const rowLane = (row) => {
    const start = moment(row, startAt);
    const end = moment(row, endAt);
    const label = text(row, labelAt) || say("untitled");
    const tone = isPast(row) ? "muted" : "accent";

    // An end with no start is a dated instant, not a stretch of work.
    if (start === null) {
      if (end === null) return null;
      return {
        label: label,
        spans: [{ kind: "milestone", label: label, start: end, end: end, tone: tone }],
      };
    }
    return {
      label: label,
      spans: [
        {
          kind: "bar",
          label: label,
          start: start,
          end: Math.max(end === null ? start + DAY : end, start + DAY),
          tone: tone,
        },
      ],
    };
  };

  /** Which lane a row belongs to — the column the author mapped to `group`, or
   *  no grouping at all when they mapped none. */
  const groupKeys = (row) => {
    if (grouping === "none" || groupAt === undefined) return [];
    return [text(row, groupAt) || say("noGroup")];
  };

  /** The lanes, plus the total row above them. `done`/`total` are the real
   *  counts rather than a sum over the groups — under the resource view a task
   *  with two owners is on two rows but is still one task. */
  const withRollup = (label, lanes, done, total) => {
    const ordered = lanes.slice().sort(byStart);
    if (!wantRollup) return ordered;
    const extent = extentOf(ordered);
    if (!extent) return ordered;
    return [
      {
        label: label,
        caption: done + "/" + total,
        tone: "muted",
        spans: [
          {
            kind: "summary",
            label: label,
            start: extent.start,
            end: extent.end,
            progress: share(done, total),
            tone: done >= total && total > 0 ? "positive" : "accent",
          },
        ],
      },
    ].concat(ordered);
  };

  const timeline = (lanes) => {
    const kept = lanes.filter((lane) => lane && (lane.spans.length || lane.children?.length));
    if (!kept.length) return empty(say("nothingSchedYet"));
    return { v: 1, scene: { kind: "timeline", lanes: kept, scale: scale, now: today } };
  };

  /** Group a flat list of rows into summary lanes, or leave it flat. */
  const grouped = (rows, laneOf, keysOf, doneOf, lateOf) => {
    const flat = [];
    const groups = new Map();
    for (const row of rows) {
      const lane = laneOf(row);
      if (!lane) continue;
      const keys = keysOf(row);
      if (!keys.length) {
        flat.push(lane);
        continue;
      }
      for (const key of keys) {
        let group = groups.get(key);
        if (!group) {
          group = { children: [], done: 0, total: 0, late: false };
          groups.set(key, group);
        }
        group.children.push(lane);
        group.total += 1;
        if (doneOf(row)) group.done += 1;
        if (lateOf(row)) group.late = true;
      }
    }
    const lanes = [];
    for (const entry of groups.entries()) {
      const group = entry[1];
      const lane = summaryLane(
        entry[0],
        group.children.slice().sort(byStart),
        group.done,
        group.total,
        groupTone(group.done, group.total, group.late)
      );
      if (lane) lanes.push(lane);
    }
    return lanes.concat(flat);
  };

  const rows = data.rows || [];
  if (!rows.length) return empty(say("noRows"));
  if (startAt === undefined && endAt === undefined) return empty(say("needDates"));

  const lanes = grouped(rows, rowLane, groupKeys, isPast, () => false);
  return timeline(withRollup(say("everything"), lanes, rows.filter(isPast).length, rows.length));
}
