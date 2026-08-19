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
        en: "Group rows by",
        de: "Zeilen gruppieren nach",
        es: "Agrupar filas por",
        fr: "Grouper les lignes par",
      },
      values: {
        project: {
          en: "Project",
          de: "Projekt",
          es: "Proyecto",
          fr: "Projet",
        },
        status: {
          en: "Status",
          de: "Status",
          es: "Estado",
          fr: "Statut",
        },
        priority: {
          en: "Priority",
          de: "Priorität",
          es: "Prioridad",
          fr: "Priorité",
        },
        assignee: {
          en: "Assignee",
          de: "Zuständig",
          es: "Responsable",
          fr: "Responsable",
        },
        none: {
          en: "Nothing — one row each",
          de: "Nichts – eine Zeile pro Eintrag",
          es: "Nada: una fila por elemento",
          fr: "Rien — une ligne par élément",
        },
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
function render(data, config) {
  const DAY = 86400000;
  const scale = config.scale || "week";
  const grouping = config.group || "project";
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

  const isDone = (task) => task.statusCategory === "done";
  const isOverdue = (task) => !isDone(task) && has(task.dueDate) && task.dueDate < today;

  /** One task as its own row. Returns null for a task with no dates at all —
   *  it has nowhere to sit on an axis, and a zero-width bar at an arbitrary
   *  point would be a lie rather than a gap. */
  const taskLane = (task) => {
    const done = isDone(task);
    const tone = done ? "positive" : isOverdue(task) ? "negative" : "accent";
    const who = task.assignees?.length ? task.assignees.join(", ") : undefined;

    // A due date with no start is a dated instant, not a stretch of work.
    if (!has(task.startDate)) {
      if (!has(task.dueDate)) return null;
      return {
        label: task.title,
        spans: [
          {
            kind: "milestone",
            label: task.title,
            start: task.dueDate,
            end: task.dueDate,
            tone: tone,
            progress: done ? 1 : 0,
            caption: who,
          },
        ],
      };
    }

    const planned = has(task.dueDate)
      ? Math.max(task.dueDate, task.startDate)
      : task.startDate + DAY;
    // A finished task draws what happened; what was planned stays as a ghost
    // beneath it, so an overrun reads as the gap between the two.
    const actual = done && has(task.completedAt) ? task.completedAt : planned;
    const span = {
      kind: "bar",
      label: task.title,
      start: task.startDate,
      end: Math.max(actual, task.startDate + DAY),
      tone: tone,
      progress: done ? 1 : 0,
      caption: who,
    };
    if (done && has(task.completedAt) && Math.abs(task.completedAt - planned) >= DAY) {
      span.baseline = { start: task.startDate, end: Math.max(planned, task.startDate + DAY) };
    }
    return { label: task.title, spans: [span] };
  };

  /** Which lane(s) a task belongs to. Assignee is the resource view: a task
   *  with two owners appears on both rows, which is the whole point of looking
   *  at a schedule that way. */
  const groupKeys = (task) => {
    if (grouping === "status") return [task.status || "No status"];
    if (grouping === "priority") return [task.priority || "No priority"];
    if (grouping === "assignee") {
      return task.assignees?.length ? task.assignees : ["Unassigned"];
    }
    if (grouping === "project") return [task.projectName || "No project"];
    return [];
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
    if (!kept.length) return empty("Nothing is scheduled yet");
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

  switch (data.source) {
    case "tasks": {
      const rows = data.rows || [];
      if (!rows.length) return empty("No tasks match");
      const lanes = grouped(rows, taskLane, groupKeys, isDone, isOverdue);
      const done = rows.filter(isDone).length;
      return timeline(withRollup("All tasks", lanes, done, rows.length));
    }

    case "projects": {
      const rows = data.rows || [];
      if (!rows.length) return empty("No projects match");

      // The tasks arrive on the same envelope the progress columns were counted
      // from, so a project folds open onto its own work without a second
      // binding. An older host that sends none simply yields groups with
      // nothing under them.
      const byProject = new Map();
      for (const task of data.tasks || []) {
        if (!has(task.projectId)) continue;
        const list = byProject.get(task.projectId);
        if (list) list.push(task);
        else byProject.set(task.projectId, [task]);
      }

      const lanes = [];
      for (const project of rows) {
        const own = byProject.get(project.id) || [];
        const children = grouping === "none" ? [] : own.map(taskLane).filter(Boolean).sort(byStart);
        const extent = extentOf(children);
        // The project's own dates are the plan. Where it has none, the work
        // under it stands in for them rather than dropping the row.
        const start = has(project.startDate) ? project.startDate : extent ? extent.start : null;
        const end = has(project.endDate) ? project.endDate : extent ? extent.end : null;
        if (!has(start)) continue;

        const total = project.taskCount || own.length;
        const done = project.doneCount || 0;
        const late = own.some(isOverdue) || (has(end) && end < today && done < total);
        const tone = groupTone(done, total, late);
        lanes.push({
          label: project.name,
          caption: done + "/" + total,
          tone: tone,
          collapsed: startFolded,
          children: children,
          spans: [
            {
              kind: "summary",
              label: project.name,
              start: start,
              end: Math.max(has(end) ? end : start, start + DAY),
              tone: tone,
              progress: total > 0 ? share(done, total) : project.progress || 0,
            },
          ],
        });
      }

      // The total row counts *projects*, not their tasks: "two of five delivered"
      // is what a portfolio row is for.
      const complete = rows.filter(
        (project) => project.taskCount > 0 && project.doneCount >= project.taskCount
      ).length;
      return timeline(withRollup("All projects", lanes, complete, rows.length));
    }

    case "calendar_entries": {
      const rows = data.rows || [];
      if (!rows.length) return empty("Nothing scheduled");
      const past = (entry) => entry.end < today;
      const entryLane = (entry) => {
        const long = entry.allDay || entry.end - entry.start >= DAY;
        return {
          label: entry.title,
          spans: [
            {
              kind: long ? "bar" : "milestone",
              label: entry.title,
              start: entry.start,
              end: Math.max(entry.end, entry.start + (entry.allDay ? DAY : 0)),
              tone: past(entry) ? "muted" : "accent",
            },
          ],
        };
      };
      // Nothing about a calendar entry answers "which project" or "whose
      // priority", so every grouping but "none" means the calendar it sits on.
      const keysOf = (entry) => (grouping === "none" ? [] : [entry.calendarName || "Calendar"]);
      const lanes = grouped(rows, entryLane, keysOf, past, () => false);
      return timeline(withRollup("Everything", lanes, rows.filter(past).length, rows.length));
    }

    default:
      return empty("This widget cannot draw " + data.source);
  }
}
