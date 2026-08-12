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
    en: "Agenda",
    de: "Agenda",
    es: "Agenda",
    fr: "Agenda",
  },
  description: {
    en: "What is coming up next — and what is already late.",
    de: "Was als Nächstes ansteht – und was bereits überfällig ist.",
    es: "Lo próximo que viene, y lo que ya va con retraso.",
    fr: "Ce qui arrive ensuite, et ce qui est déjà en retard.",
  },
};

/**
 * Built-in: agenda — the next things, in order.
 *
 * The one built-in that reads the clock: events still ahead (or under way)
 * sorted by start, or open tasks sorted by due date with late ones flagged.
 * The host freezes `Date.now()` — to the real minute on a live tile, to the
 * sample anchor in a preview — so the same inputs always draw the same list.
 *
 * @param {import("../dataShapes").WidgetData} data
 * @param {import("../dataShapes").WidgetConfig} config
 */
function render(data, config) {
  const now = Date.now();
  const empty = (message) => ({ v: 1, scene: { kind: "empty", message } });

  const table = (columns, rows) => ({ v: 1, scene: { kind: "table", columns, rows } });

  switch (data.source) {
    case "calendar_entries": {
      const rows = data.rows || [];
      if (!rows.length) return empty("Nothing scheduled");
      // Under way still belongs on an agenda; only what has fully ended drops.
      const ahead = rows
        .filter((entry) => entry.end >= now)
        .sort((a, b) => a.start - b.start || (a.title < b.title ? -1 : 1));
      if (!ahead.length) return empty("Nothing scheduled ahead");
      return table(
        [
          { key: "when", label: "When", format: "date", align: "end" },
          { key: "title", label: "Event" },
          { key: "calendar", label: "Calendar" },
        ],
        ahead.map((entry) => ({
          when: entry.start,
          title: entry.title,
          calendar: entry.calendarName,
        }))
      );
    }

    case "tasks": {
      const rows = data.rows || [];
      if (!rows.length) return empty("No tasks match");
      // Open work with a date to sit on. A task without a due date has no
      // place in a time-ordered list, and finished work is no longer ahead.
      const due = rows
        .filter((task) => task.statusCategory !== "done" && task.dueDate !== null)
        .sort((a, b) => a.dueDate - b.dueDate || (a.title < b.title ? -1 : 1));
      if (!due.length) return empty("Nothing due");
      return table(
        [
          { key: "due", label: "Due", format: "date", align: "end" },
          { key: "title", label: "Task" },
          { key: "project", label: "Project" },
          { key: "status", label: "Status" },
        ],
        due.map((task) => ({
          due: task.dueDate,
          title: task.title,
          project: task.projectName,
          status: task.dueDate < now ? "Overdue" : task.status,
        }))
      );
    }

    default:
      return empty("This widget cannot draw " + data.source);
  }
}
