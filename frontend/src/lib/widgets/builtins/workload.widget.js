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
    en: "Workload",
    de: "Auslastung",
    es: "Carga de trabajo",
    fr: "Charge de travail",
  },
  description: {
    en: "How the open work is spread across the team, split by status.",
    de: "Wie sich die offene Arbeit über das Team verteilt, aufgeteilt nach Status.",
    es: "Cómo se reparte el trabajo abierto entre el equipo, dividido por estado.",
    fr: "Comment le travail en cours se répartit dans l'équipe, ventilé par statut.",
  },
  options: {
    stacked: {
      label: {
        en: "Stacked",
        de: "Gestapelt",
        es: "Apilado",
        fr: "Empilé",
      },
      values: {
        true: {
          en: "Stacked",
          de: "Gestapelt",
          es: "Apilado",
          fr: "Empilé",
        },
        false: {
          en: "Side by side",
          de: "Nebeneinander",
          es: "Lado a lado",
          fr: "Côte à côte",
        },
      },
    },
  },
};

/**
 * Built-in: workload — open work per person.
 *
 * Finished work is not load, so done tasks are left out; what remains is
 * grouped per person and split by status category, heaviest load first. Tasks
 * with no one on them stand in their own "Unassigned" column — orphaned work
 * is exactly what a workload view exists to surface. A task with several
 * assignees counts once for each of them.
 *
 * @param {import("../dataShapes").WidgetData} data
 * @param {import("../dataShapes").WidgetConfig} config
 */
function render(data, config) {
  const empty = (message) => ({ v: 1, scene: { kind: "empty", message } });

  switch (data.source) {
    case "tasks": {
      const rows = data.rows || [];
      if (!rows.length) return empty("No tasks match");

      const open = rows.filter((task) => task.statusCategory !== "done");
      if (!open.length) return empty("No open work");

      const totals = new Map();
      const byCategory = new Map();
      for (const task of open) {
        const people = task.assignees.length ? task.assignees : ["Unassigned"];
        let counts = byCategory.get(task.statusCategory);
        if (!counts) {
          counts = new Map();
          byCategory.set(task.statusCategory, counts);
        }
        for (const person of people) {
          totals.set(person, (totals.get(person) || 0) + 1);
          counts.set(person, (counts.get(person) || 0) + 1);
        }
      }

      const order = [...totals.entries()]
        .sort(([aName, a], [bName, b]) => b - a || (aName < bName ? -1 : 1))
        .map(([person]) => person);

      // Workflow order, not size order: to-do before in-progress reads as the
      // pipeline it is. Unknown categories keep their own names and follow.
      const KNOWN = [
        { category: "todo", label: "To do", tone: "neutral" },
        { category: "in_progress", label: "In progress", tone: "accent" },
      ];
      const known = KNOWN.filter(({ category }) => byCategory.has(category));
      const rest = [...byCategory.keys()]
        .filter((category) => !KNOWN.some((entry) => entry.category === category))
        .sort()
        .map((category) => ({ category, label: category, tone: undefined }));

      const series = [...known, ...rest].map(({ category, label, tone }) => ({
        name: label,
        tone,
        points: order.map((person) => ({
          x: person,
          y: byCategory.get(category).get(person) || 0,
        })),
      }));

      return {
        v: 1,
        scene: {
          kind: "series",
          mark: "bar",
          stacked: config.stacked !== "false",
          series,
          showLegend: series.length > 1,
        },
      };
    }

    default:
      return empty("This widget cannot draw " + data.source);
  }
}
