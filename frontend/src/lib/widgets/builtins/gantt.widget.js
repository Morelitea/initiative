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
    en: "Scheduled work as bars on a shared timeline, grouped into lanes.",
    de: "Geplante Arbeit als Balken auf einer gemeinsamen Zeitachse, in Spuren gruppiert.",
    es: "El trabajo programado como barras en una línea de tiempo común, agrupado en carriles.",
    fr: "Le travail planifié sous forme de barres sur une frise commune, regroupées en couloirs.",
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
  },
};

/**
 * Built-in: Gantt — spans on a time axis, grouped into lanes.
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

  const timeline = (lanes) => {
    const withSpans = lanes.filter((lane) => lane.spans.length);
    if (!withSpans.length) {
      return { v: 1, scene: { kind: "empty", message: "Nothing scheduled" } };
    }
    return { v: 1, scene: { kind: "timeline", lanes: withSpans, scale } };
  };

  const empty = (message) => ({ v: 1, scene: { kind: "empty", message } });

  /** A span needs both ends. One-sided dates get a one-day bar at the end we
   *  know, which keeps a task with only a due date visible instead of dropped. */
  const span = (label, start, end, tone, progress) => {
    const from = start !== null && start !== undefined ? start : end;
    const to = end !== null && end !== undefined ? end : start;
    if (from === null || from === undefined) return null;
    return {
      label,
      start: from,
      end: Math.max(to, from + DAY),
      tone: tone || undefined,
      progress: progress === undefined ? undefined : progress,
    };
  };

  // `Date.now()` is the host's clock, frozen for this render — the sandbox's
  // deterministic shim, not the wall clock. That is enough to mark a task late.
  const today = Date.now();
  const toneForTask = (task) => {
    if (task.statusCategory === "done") return "positive";
    return task.dueDate !== null && task.dueDate < today ? "negative" : "accent";
  };

  switch (data.source) {
    case "tasks": {
      const rows = data.rows || [];
      if (!rows.length) return empty("No tasks match");
      // One lane per project keeps a cross-project view readable; tasks with no
      // project share an "Unassigned" lane rather than vanishing.
      const lanes = new Map();
      for (const task of rows) {
        const key = task.projectName || "Unassigned";
        if (!lanes.has(key)) lanes.set(key, []);
        const bar = span(
          task.title,
          task.startDate,
          task.dueDate,
          toneForTask(task),
          task.statusCategory === "done" ? 1 : undefined
        );
        if (bar) lanes.get(key).push(bar);
      }
      return timeline([...lanes.entries()].map(([label, spans]) => ({ label, spans })));
    }

    case "projects": {
      const rows = data.rows || [];
      if (!rows.length) return empty("No projects match");
      return timeline(
        rows.map((project) => {
          const bar = span(
            project.name,
            project.startDate,
            project.endDate,
            project.progress >= 1 ? "positive" : "accent",
            project.progress
          );
          return { label: project.name, spans: bar ? [bar] : [] };
        })
      );
    }

    case "calendar_entries": {
      const rows = data.rows || [];
      if (!rows.length) return empty("Nothing scheduled");
      const lanes = new Map();
      for (const entry of rows) {
        const key = entry.calendarName || "Calendar";
        if (!lanes.has(key)) lanes.set(key, []);
        const bar = span(entry.title, entry.start, entry.end, "accent");
        if (bar) lanes.get(key).push(bar);
      }
      return timeline([...lanes.entries()].map(([label, spans]) => ({ label, spans })));
    }

    default:
      return empty("This widget cannot draw " + data.source);
  }
}
