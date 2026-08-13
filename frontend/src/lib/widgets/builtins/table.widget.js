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
    en: "Table",
    de: "Tabelle",
    es: "Tabla",
    fr: "Tableau",
  },
  description: {
    en: "A plain read-only grid of rows and columns.",
    de: "Ein einfaches, schreibgeschütztes Raster aus Zeilen und Spalten.",
    es: "Una cuadrícula sencilla de solo lectura con filas y columnas.",
    fr: "Une simple grille en lecture seule, en lignes et colonnes.",
  },
};

/**
 * Built-in: table — a plain read-only grid.
 *
 * Display only, and pointedly so: no row actions, no inline editing, no
 * check-off. Working with tasks is a project view's job (§6.1 of the design) —
 * this shows what is there and nothing more.
 *
 * @param {import("../dataShapes").WidgetData} data
 * @param {import("../dataShapes").WidgetConfig} config
 */
function render(data, config) {
  const empty = (message) => ({ v: 1, scene: { kind: "empty", message } });

  const table = (columns, rows) => {
    if (!rows.length) return empty("Nothing to show");
    return { v: 1, scene: { kind: "table", columns, rows } };
  };

  // The renderer formats dates; the widget only says which columns are dates.
  const dateColumn = (key, label) => ({ key, label, format: "date", align: "end" });
  const numberColumn = (key, label) => ({ key, label, align: "end" });

  switch (data.source) {
    case "tasks": {
      const rows = data.rows || [];
      if (!rows.length) return empty("No tasks match");
      return table(
        [
          { key: "title", label: "Task" },
          { key: "project", label: "Project" },
          { key: "status", label: "Status" },
          dateColumn("due", "Due"),
        ],
        rows.map((task) => ({
          title: task.title,
          project: task.projectName,
          status: task.status,
          due: task.dueDate,
        }))
      );
    }

    case "projects": {
      const rows = data.rows || [];
      if (!rows.length) return empty("No projects match");
      return table(
        [
          { key: "name", label: "Project" },
          numberColumn("tasks", "Tasks"),
          numberColumn("done", "Done"),
          { key: "progress", label: "Progress", align: "end", format: "percent" },
        ],
        rows.map((project) => ({
          name: project.name,
          tasks: project.taskCount,
          done: project.doneCount,
          progress: project.progress,
        }))
      );
    }

    case "calendar_entries": {
      const rows = data.rows || [];
      if (!rows.length) return empty("Nothing scheduled");
      return table(
        [
          { key: "title", label: "Event" },
          { key: "calendar", label: "Calendar" },
          dateColumn("start", "Starts"),
          dateColumn("end", "Ends"),
        ],
        rows.map((entry) => ({
          title: entry.title,
          calendar: entry.calendarName,
          start: entry.start,
          end: entry.end,
        }))
      );
    }

    case "sheet_range": {
      const range = data.range;
      if (!range?.rows.length) return empty("Range is empty");
      // A sheet's own header row names the columns; keys are positional so a
      // duplicated or blank header can't collapse two columns into one.
      const columns = range.columns.slice(0, 12).map((label, index) => ({
        key: "c" + index,
        label: label || "Column " + (index + 1),
        align: typeof range.rows[0][index] === "number" ? "end" : "start",
      }));
      return table(
        columns,
        range.rows.map((row) => {
          const record = {};
          for (let index = 0; index < columns.length; index++) {
            record[columns[index].key] = row[index] === undefined ? null : row[index];
          }
          return record;
        })
      );
    }

    default:
      return empty("This widget cannot draw " + data.source);
  }
}
