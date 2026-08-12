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
    en: "Leaderboard",
    de: "Bestenliste",
    es: "Clasificación",
    fr: "Classement",
  },
  description: {
    en: "People ranked by finished work, with what each still has open.",
    de: "Personen nach erledigter Arbeit geordnet, mit dem, was jeweils noch offen ist.",
    es: "Personas ordenadas por trabajo terminado, con lo que cada una tiene abierto.",
    fr: "Les personnes classées par travail terminé, avec ce qui reste ouvert à chacune.",
  },
};

/**
 * Built-in: leaderboard — ranked standings.
 *
 * From task rows it ranks people by what they have finished; from a
 * pre-aggregated count it ranks whatever the binding grouped by. A task with
 * several assignees counts once for each of them — the same reading the count
 * source's own assignee grouping uses.
 *
 * @param {import("../dataShapes").WidgetData} data
 * @param {import("../dataShapes").WidgetConfig} config
 */
function render(data, config) {
  const empty = (message) => ({ v: 1, scene: { kind: "empty", message } });

  const table = (columns, rows) => ({ v: 1, scene: { kind: "table", columns, rows } });

  const rankColumn = { key: "rank", label: "#", align: "end" };

  switch (data.source) {
    case "tasks": {
      const rows = data.rows || [];
      if (!rows.length) return empty("No tasks match");

      const standings = new Map();
      for (const task of rows) {
        for (const person of task.assignees) {
          const entry = standings.get(person) || { done: 0, open: 0 };
          if (task.statusCategory === "done") entry.done += 1;
          else entry.open += 1;
          standings.set(person, entry);
        }
      }
      if (!standings.size) return empty("No assigned work");

      const ranked = [...standings.entries()].sort(
        ([aName, a], [bName, b]) => b.done - a.done || b.open - a.open || (aName < bName ? -1 : 1)
      );
      return table(
        [
          rankColumn,
          { key: "person", label: "Person" },
          { key: "done", label: "Done", align: "end" },
          { key: "open", label: "Open", align: "end" },
        ],
        ranked.map(([person, entry], index) => ({
          rank: index + 1,
          person,
          done: entry.done,
          open: entry.open,
        }))
      );
    }

    case "task_counts": {
      const rows = data.rows || [];
      if (!rows.length) return empty("No tasks match");
      const ranked = [...rows].sort((a, b) => b.count - a.count || (a.bucket < b.bucket ? -1 : 1));
      return table(
        [
          rankColumn,
          { key: "name", label: "Name" },
          { key: "count", label: "Tasks", align: "end" },
        ],
        ranked.map((row, index) => ({ rank: index + 1, name: row.bucket, count: row.count }))
      );
    }

    default:
      return empty("This widget cannot draw " + data.source);
  }
}
