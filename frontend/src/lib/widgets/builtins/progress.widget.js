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
function render(data, config) {
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
    if (!nodes.length) return empty("Nothing to measure");
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
      if (!counter) return empty("No counter selected");
      const min = counter.min === null || counter.min === undefined ? 0 : counter.min;
      const max = counter.max === null || counter.max === undefined ? counter.value : counter.max;
      const caption = counter.value + " of " + max + (counter.unit ? " " + counter.unit : "");
      return {
        v: 1,
        scene: meter(counter.name, counter.value, min, max, caption, "accent"),
      };
    }

    case "task_counts": {
      const rows = data.rows || [];
      if (!rows.length) return empty("No tasks match");

      let total = 0;
      for (const row of rows) total += row.count;

      if (each) {
        return column(
          rows.map((row) =>
            meter(row.bucket, row.count, 0, total, row.count + " of " + total, "accent")
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
        scene: meter("Done", done, 0, total, done + " of " + total, shareTone(done, total, false)),
      };
    }

    case "projects": {
      const rows = data.rows || [];
      if (!rows.length) return empty("No projects match");

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
              project.doneCount + " of " + project.taskCount,
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
          rows.length + " projects",
          done,
          0,
          tasks || 1,
          done + " of " + tasks,
          shareTone(done, tasks, late)
        ),
      };
    }

    default:
      return empty("This widget cannot draw " + data.source);
  }
}
