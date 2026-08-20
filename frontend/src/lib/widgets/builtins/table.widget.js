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
  nothingScheduled: {
    en: "Nothing scheduled",
    de: "Nichts geplant",
    es: "Nada programado",
    fr: "Rien de planifié",
  },
  rangeEmpty: {
    en: "Range is empty",
    de: "Bereich ist leer",
    es: "El rango está vacío",
    fr: "La plage est vide",
  },
  nothingToShow: {
    en: "Nothing to show",
    de: "Nichts anzuzeigen",
    es: "Nada que mostrar",
    fr: "Rien à afficher",
  },
  cannotDraw: {
    en: "This widget cannot draw ",
    de: "Dieses Widget kann das nicht zeichnen: ",
    es: "Este widget no puede dibujar ",
    fr: "Ce widget ne peut pas dessiner ",
  },
  task: { en: "Task", de: "Aufgabe", es: "Tarea", fr: "Tâche" },
  project: { en: "Project", de: "Projekt", es: "Proyecto", fr: "Projet" },
  status: { en: "Status", de: "Status", es: "Estado", fr: "Statut" },
  due: { en: "Due", de: "Fällig", es: "Vence", fr: "Échéance" },
  assignees: { en: "Assignees", de: "Zuständig", es: "Responsables", fr: "Responsables" },
  priority: { en: "Priority", de: "Priorität", es: "Prioridad", fr: "Priorité" },
  tags: { en: "Tags", de: "Tags", es: "Etiquetas", fr: "Étiquettes" },
  checklist: { en: "Checklist", de: "Checkliste", es: "Lista", fr: "Liste" },
  comments: { en: "Comments", de: "Kommentare", es: "Comentarios", fr: "Commentaires" },
  tasks: { en: "Tasks", de: "Aufgaben", es: "Tareas", fr: "Tâches" },
  done: { en: "Done", de: "Erledigt", es: "Hecho", fr: "Terminé" },
  progress: { en: "Progress", de: "Fortschritt", es: "Progreso", fr: "Avancement" },
  owner: { en: "Owner", de: "Eigentümer", es: "Propietario", fr: "Propriétaire" },
  ends: { en: "Ends", de: "Endet", es: "Termina", fr: "Fin" },
  starts: { en: "Starts", de: "Beginnt", es: "Empieza", fr: "Début" },
  event: { en: "Event", de: "Termin", es: "Evento", fr: "Événement" },
  calendar: { en: "Calendar", de: "Kalender", es: "Calendario", fr: "Calendrier" },
  location: { en: "Location", de: "Ort", es: "Ubicación", fr: "Lieu" },
  who: { en: "Who", de: "Wer", es: "Quién", fr: "Qui" },
  total: { en: "Total", de: "Gesamt", es: "Total", fr: "Total" },
  column: { en: "Column", de: "Spalte", es: "Columna", fr: "Colonne" },
  projects: { en: "projects", de: "Projekte", es: "proyectos", fr: "projets" },
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
function render(data, config, context) {
  // The viewer's language, and this module's own words in it. An older host
  // that passes no context leaves this at English rather than failing.
  const lang = context?.locale || "en";
  const say = (key) => {
    const entry = strings[key] || {};
    return entry[lang] || entry[lang.split("-")[0]] || entry.en || key;
  };
  const detailed = config.columns === "detailed";
  const markOverdue = config.highlight === "overdue";
  const wantTotals = config.totals === "on";
  // The clock the host handed us. A widget must never invent one.
  const today = Date.now();

  const empty = (message) => ({ v: 1, scene: { kind: "empty", message } });

  const table = (columns, rows) => {
    if (!rows.length) return empty(say("nothingToShow"));
    return { v: 1, scene: { kind: "table", columns: columns, rows: rows } };
  };

  // The renderer formats dates; the widget only says which columns are dates.
  const dateColumn = (key, label) => ({ key: key, label: label, format: "date", align: "end" });
  const numberColumn = (key, label) => ({ key: key, label: label, align: "end" });

  /** A value that should read as late. Tone travels with the cell, and the
   *  renderer resolves it to a theme token like every other. */
  const overdue = (value, isLate) =>
    markOverdue && isLate ? { value: value, tone: "negative" } : value;

  const join = (list) => (list?.length ? list.join(", ") : null);

  switch (data.source) {
    case "tasks": {
      const rows = data.rows || [];
      if (!rows.length) return empty(say("noTasks"));

      const columns = [
        { key: "title", label: say("task") },
        { key: "project", label: say("project") },
        { key: "status", label: say("status") },
        dateColumn("due", say("due")),
      ];
      if (detailed) {
        columns.splice(3, 0, { key: "assignees", label: say("assignees") });
        columns.push(
          { key: "priority", label: say("priority") },
          { key: "tags", label: say("tags") },
          { key: "checklist", label: say("checklist"), align: "end" },
          numberColumn("comments", say("comments"))
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
          title: rows.length + " " + say("tasks"),
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
      if (!rows.length) return empty(say("noProjects"));

      const columns = [
        { key: "name", label: say("project") },
        numberColumn("tasks", say("tasks")),
        numberColumn("done", say("done")),
        { key: "progress", label: say("progress"), align: "end", format: "percent" },
      ];
      if (detailed) {
        columns.splice(1, 0, { key: "owner", label: say("owner") });
        columns.push(dateColumn("end", say("ends")), { key: "tags", label: say("tags") });
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
          name: rows.length + " " + say("projects"),
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
      if (!rows.length) return empty(say("nothingScheduled"));

      const columns = [
        { key: "title", label: say("event") },
        { key: "calendar", label: say("calendar") },
        dateColumn("start", say("starts")),
        dateColumn("end", say("ends")),
      ];
      if (detailed) {
        columns.push(
          { key: "location", label: say("location") },
          { key: "attendees", label: say("who") }
        );
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
      if (!range?.rows.length) return empty(say("rangeEmpty"));
      // A sheet's own header row names the columns; keys are positional so a
      // duplicated or blank header can't collapse two columns into one.
      const columns = range.columns.slice(0, 12).map((label, index) => ({
        key: "c" + index,
        label: label || say("column") + " " + (index + 1),
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
            totals[columns[index].key] = index === 0 ? say("total") : null;
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
      return empty(say("cannotDraw") + data.source);
  }
}
