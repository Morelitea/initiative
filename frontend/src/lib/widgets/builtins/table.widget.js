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
  options: {
    columns: {
      label: {
        en: "Columns",
        de: "Spalten",
        es: "Columnas",
        fr: "Colonnes",
      },
      values: {
        standard: {
          en: "The essentials",
          de: "Das Wesentliche",
          es: "Lo esencial",
          fr: "L'essentiel",
        },
        detailed: {
          en: "Everything the row carries",
          de: "Alles, was die Zeile enthält",
          es: "Todo lo que trae la fila",
          fr: "Tout ce que la ligne contient",
        },
      },
    },
    highlight: {
      label: {
        en: "Highlight",
        de: "Hervorheben",
        es: "Destacar",
        fr: "Mettre en avant",
      },
      values: {
        off: { en: "Nothing", de: "Nichts", es: "Nada", fr: "Rien" },
        overdue: {
          en: "Anything overdue",
          de: "Alles Überfällige",
          es: "Todo lo vencido",
          fr: "Tout ce qui est en retard",
        },
      },
    },
    totals: {
      label: {
        en: "Totals row",
        de: "Summenzeile",
        es: "Fila de totales",
        fr: "Ligne de totaux",
      },
      values: {
        off: { en: "Hide", de: "Ausblenden", es: "Ocultar", fr: "Masquer" },
        on: { en: "Show", de: "Anzeigen", es: "Mostrar", fr: "Afficher" },
      },
    },
  },
};

/**
 * Built-in: table — a read-only grid over whatever the binding returns.
 *
 * Display only, and pointedly so: no row actions, no inline editing, no
 * check-off. Working with tasks is a project view's job — this shows what is
 * there and nothing more.
 *
 * The envelope now carries far more than the four columns this used to show, so
 * "detailed" opens up tags, assignees, checklist progress and comment counts.
 * `highlight` is why a cell may carry a tone: an overdue date reading red is
 * the difference between a table you scan and a table you read.
 *
 * @param {import("../dataShapes").WidgetData} data
 * @param {import("../dataShapes").WidgetConfig} config
 */
function render(data, config) {
  const detailed = config.columns === "detailed";
  const markOverdue = config.highlight === "overdue";
  const wantTotals = config.totals === "on";
  // The clock the host handed us. A widget must never invent one.
  const today = Date.now();

  const empty = (message) => ({ v: 1, scene: { kind: "empty", message } });

  const table = (columns, rows) => {
    if (!rows.length) return empty("Nothing to show");
    return { v: 1, scene: { kind: "table", columns: columns, rows: rows } };
  };

  // The renderer formats dates; the widget only says which columns are dates.
  const dateColumn = (key, label) => ({ key: key, label: label, format: "date", align: "end" });
  const numberColumn = (key, label) => ({ key: key, label: label, align: "end" });

  /** A value that should read as late. Tone travels with the cell, and the
   *  renderer resolves it to a theme token like every other. */
  const overdue = (value, isLate) =>
    markOverdue && isLate ? { value: value, tone: "negative" } : value;

  const join = (list) => (list && list.length ? list.join(", ") : null);

  switch (data.source) {
    case "tasks": {
      const rows = data.rows || [];
      if (!rows.length) return empty("No tasks match");

      const columns = [
        { key: "title", label: "Task" },
        { key: "project", label: "Project" },
        { key: "status", label: "Status" },
        dateColumn("due", "Due"),
      ];
      if (detailed) {
        columns.splice(3, 0, { key: "assignees", label: "Assignees" });
        columns.push(
          { key: "priority", label: "Priority" },
          { key: "tags", label: "Tags" },
          { key: "checklist", label: "Checklist", align: "end" },
          numberColumn("comments", "Comments")
        );
      }

      const body = rows.map((task) => {
        const late =
          task.statusCategory !== "done" && task.dueDate !== null && task.dueDate < today;
        const row = {
          title: task.title,
          project: task.projectName,
          status: task.status,
          due: overdue(task.dueDate, late),
        };
        if (detailed) {
          row.assignees = join(task.assignees);
          row.priority = task.priority;
          row.tags = join(task.tags);
          row.checklist = task.subtaskTotal ? task.subtaskDone + "/" + task.subtaskTotal : null;
          row.comments = task.commentCount;
        }
        return row;
      });

      if (wantTotals) {
        let comments = 0;
        for (const task of rows) comments += task.commentCount;
        body.push({
          title: rows.length + " tasks",
          project: null,
          status: null,
          due: null,
          assignees: null,
          priority: null,
          tags: null,
          checklist: null,
          comments: detailed ? comments : null,
        });
      }
      return table(columns, body);
    }

    case "projects": {
      const rows = data.rows || [];
      if (!rows.length) return empty("No projects match");

      const columns = [
        { key: "name", label: "Project" },
        numberColumn("tasks", "Tasks"),
        numberColumn("done", "Done"),
        { key: "progress", label: "Progress", align: "end", format: "percent" },
      ];
      if (detailed) {
        columns.splice(1, 0, { key: "owner", label: "Owner" });
        columns.push(dateColumn("end", "Ends"), { key: "tags", label: "Tags" });
      }

      const body = rows.map((project) => {
        const late =
          project.endDate !== null &&
          project.endDate < today &&
          project.doneCount < project.taskCount;
        const row = {
          name: project.name,
          tasks: project.taskCount,
          done: project.doneCount,
          progress: project.progress,
        };
        if (detailed) {
          row.owner = project.ownerName;
          row.end = overdue(project.endDate, late);
          row.tags = join(project.tags);
        }
        return row;
      });

      if (wantTotals) {
        let tasks = 0;
        let done = 0;
        for (const project of rows) {
          tasks += project.taskCount;
          done += project.doneCount;
        }
        body.push({
          name: rows.length + " projects",
          owner: null,
          tasks: tasks,
          done: done,
          progress: tasks > 0 ? done / tasks : 0,
          end: null,
          tags: null,
        });
      }
      return table(columns, body);
    }

    case "calendar_entries": {
      const rows = data.rows || [];
      if (!rows.length) return empty("Nothing scheduled");

      const columns = [
        { key: "title", label: "Event" },
        { key: "calendar", label: "Calendar" },
        dateColumn("start", "Starts"),
        dateColumn("end", "Ends"),
      ];
      if (detailed) {
        columns.push({ key: "location", label: "Location" }, { key: "attendees", label: "Who" });
      }

      return table(
        columns,
        rows.map((entry) => {
          const row = {
            title: entry.title,
            calendar: entry.calendarName,
            start: entry.start,
            end: entry.end,
          };
          if (detailed) {
            row.location = entry.location;
            row.attendees = join(entry.attendees);
          }
          return row;
        })
      );
    }

    case "sheet_range": {
      const range = data.range;
      if (!range || !range.rows.length) return empty("Range is empty");
      // A sheet's own header row names the columns; keys are positional so a
      // duplicated or blank header can't collapse two columns into one.
      const columns = range.columns.slice(0, 12).map((label, index) => ({
        key: "c" + index,
        label: label || "Column " + (index + 1),
        align: typeof range.rows[0][index] === "number" ? "end" : "start",
      }));
      const body = range.rows.map((row) => {
        const record = {};
        for (let index = 0; index < columns.length; index++) {
          record[columns[index].key] = row[index] === undefined ? null : row[index];
        }
        return record;
      });

      if (wantTotals) {
        const totals = {};
        for (let index = 0; index < columns.length; index++) {
          if (columns[index].align !== "end") {
            totals[columns[index].key] = index === 0 ? "Total" : null;
            continue;
          }
          let sum = 0;
          for (const row of range.rows) {
            if (typeof row[index] === "number") sum += row[index];
          }
          totals[columns[index].key] = sum;
        }
        body.push(totals);
      }
      return table(columns, body);
    }

    default:
      return empty("This widget cannot draw " + data.source);
  }
}
