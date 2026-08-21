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
  noTasks: {
    en: "No tasks match",
    de: "Keine Aufgaben passen",
    es: "Ninguna tarea coincide",
    fr: "Aucune tâche ne correspond",
  },
  noProjects: {
    en: "No projects match",
    de: "Keine Projekte passen",
    es: "Ningún proyecto coincide",
    fr: "Aucun projet ne correspond",
  },
  noCounter: {
    en: "No counter selected",
    de: "Kein Zähler ausgewählt",
    es: "Ningún contador seleccionado",
    fr: "Aucun compteur sélectionné",
  },
  nothingToMeasure: {
    en: "Nothing to measure",
    de: "Nichts zu messen",
    es: "Nada que medir",
    fr: "Rien à mesurer",
  },
  cannotDraw: {
    en: "This widget cannot draw ",
    de: "Dieses Widget kann das nicht zeichnen: ",
    es: "Este widget no puede dibujar ",
    fr: "Ce widget ne peut pas dessiner ",
  },
  done: { en: "Done", de: "Erledigt", es: "Hecho", fr: "Terminé" },
  of: { en: "of", de: "von", es: "de", fr: "sur" },
  projects: { en: "projects", de: "Projekte", es: "proyectos", fr: "projets" },
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

  switch (data.source) {
    case "counter": {
      const counter = data.counter;
      if (!counter) return empty(say("noCounter"));
      const min = counter.min === null || counter.min === undefined ? 0 : counter.min;
      const max = counter.max === null || counter.max === undefined ? counter.value : counter.max;
      const caption =
        counter.value + " " + say("of") + " " + max + (counter.unit ? " " + counter.unit : "");
      return {
        v: 1,
        scene: meter(counter.name, counter.value, min, max, caption, "accent"),
      };
    }

    case "task_counts": {
      const rows = data.rows || [];
      if (!rows.length) return empty(say("noTasks"));

      let total = 0;
      for (const row of rows) total += row.count;

      if (each) {
        return column(
          rows.map((row) =>
            meter(
              row.bucket,
              row.count,
              0,
              total,
              row.count + " " + say("of") + " " + total,
              "accent"
            )
          )
        );
      }

      // The whole binding as one bar: how much of it is finished.
      let done = 0;
      for (const row of rows) {
        if (row.bucket === "done" || row.bucket === "Done") done += row.count;
      }
      return {
        v: 1,
        scene: meter(
          say("done"),
          done,
          0,
          total,
          done + " " + say("of") + " " + total,
          shareTone(done, total, false)
        ),
      };
    }

    case "projects": {
      const rows = data.rows || [];
      if (!rows.length) return empty(say("noProjects"));

      if (each) {
        return column(
          rows.map((project) => {
            const late =
              project.endDate !== null &&
              project.endDate < today &&
              project.doneCount < project.taskCount;
            return meter(
              project.name,
              project.doneCount,
              0,
              project.taskCount || 1,
              project.doneCount + " " + say("of") + " " + project.taskCount,
              shareTone(project.doneCount, project.taskCount, late)
            );
          })
        );
      }

      let tasks = 0;
      let done = 0;
      let late = false;
      for (const project of rows) {
        tasks += project.taskCount;
        done += project.doneCount;
        if (
          project.endDate !== null &&
          project.endDate < today &&
          project.doneCount < project.taskCount
        ) {
          late = true;
        }
      }
      return {
        v: 1,
        scene: meter(
          rows.length + " " + say("projects"),
          done,
          0,
          tasks || 1,
          done + " " + say("of") + " " + tasks,
          shareTone(done, tasks, late)
        ),
      };
    }

    default:
      return empty(say("cannotDraw") + data.source);
  }
}
