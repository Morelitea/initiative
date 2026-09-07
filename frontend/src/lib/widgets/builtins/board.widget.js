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
    en: "Board",
    de: "Board",
    es: "Tablero",
    fr: "Tableau",
  },
  description: {
    en: "Tasks dealt into columns — by status, by who is on them, or by one of your own fields.",
    de: "Aufgaben in Spalten — nach Status, nach zuständiger Person oder nach einem eigenen Feld.",
    es: "Tareas repartidas en columnas: por estado, por quién las lleva o por un campo propio.",
    fr: "Les tâches réparties en colonnes : par statut, par personne en charge ou selon l'un de vos champs.",
  },
  options: {
    group: {
      label: {
        en: "Columns are",
        de: "Spalten sind",
        es: "Las columnas son",
        fr: "Les colonnes sont",
      },
      values: {
        status: { en: "Statuses", de: "Status", es: "Estados", fr: "Statuts" },
        status_category: {
          en: "Status categories",
          de: "Statuskategorien",
          es: "Categorías de estado",
          fr: "Catégories de statut",
        },
        assignee: { en: "People", de: "Personen", es: "Personas", fr: "Personnes" },
        priority: { en: "Priorities", de: "Prioritäten", es: "Prioridades", fr: "Priorités" },
        project: { en: "Projects", de: "Projekte", es: "Proyectos", fr: "Projets" },
        tag: { en: "Tags", de: "Tags", es: "Etiquetas", fr: "Étiquettes" },
        property: {
          en: "The property below",
          de: "Die Eigenschaft unten",
          es: "La propiedad de abajo",
          fr: "La propriété ci-dessous",
        },
      },
    },
    sort: {
      label: {
        en: "Cards in order of",
        de: "Karten sortiert nach",
        es: "Tarjetas ordenadas por",
        fr: "Cartes classées par",
      },
      values: {
        due: { en: "Due date", de: "Fälligkeit", es: "Fecha límite", fr: "Échéance" },
        priority: { en: "Priority", de: "Priorität", es: "Prioridad", fr: "Priorité" },
        created: {
          en: "Newest first",
          de: "Neueste zuerst",
          es: "Más recientes primero",
          fr: "Les plus récentes d'abord",
        },
        updated: {
          en: "Recently touched",
          de: "Zuletzt bearbeitet",
          es: "Modificadas hace poco",
          fr: "Modifiées récemment",
        },
        title: { en: "Name", de: "Name", es: "Nombre", fr: "Nom" },
      },
    },
    cards: {
      label: {
        en: "Cards show",
        de: "Karten zeigen",
        es: "Las tarjetas muestran",
        fr: "Les cartes montrent",
      },
      values: {
        standard: {
          en: "The essentials",
          de: "Das Wesentliche",
          es: "Lo esencial",
          fr: "L'essentiel",
        },
        compact: { en: "Titles only", de: "Nur Titel", es: "Solo títulos", fr: "Les titres seuls" },
        detailed: {
          en: "Everything the card carries",
          de: "Alles, was die Karte enthält",
          es: "Todo lo que trae la tarjeta",
          fr: "Tout ce que la carte contient",
        },
      },
    },
    highlight: {
      label: { en: "Highlight", de: "Hervorheben", es: "Destacar", fr: "Mettre en avant" },
      values: {
        overdue: {
          en: "Anything overdue",
          de: "Alles Überfällige",
          es: "Todo lo vencido",
          fr: "Tout ce qui est en retard",
        },
        off: { en: "Nothing", de: "Nichts", es: "Nada", fr: "Rien" },
      },
    },
    columns: {
      label: {
        en: "Column order",
        de: "Spaltenreihenfolge",
        es: "Orden de las columnas",
        fr: "Ordre des colonnes",
      },
      values: {
        natural: {
          en: "The field's own",
          de: "Die des Feldes",
          es: "El del propio campo",
          fr: "Celui du champ",
        },
        largest: {
          en: "Fullest first",
          de: "Vollste zuerst",
          es: "Las más llenas primero",
          fr: "Les plus remplies d'abord",
        },
        label: { en: "By name", de: "Nach Name", es: "Por nombre", fr: "Par nom" },
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
  needProperty: {
    en: "Choose which property the columns come from",
    de: "Wähle die Eigenschaft, aus der die Spalten kommen",
    es: "Elige de qué propiedad salen las columnas",
    fr: "Choisissez la propriété d'où viennent les colonnes",
  },
  cannotDraw: {
    en: "This widget cannot draw ",
    de: "Dieses Widget kann das nicht zeichnen: ",
    es: "Este widget no puede dibujar ",
    fr: "Ce widget ne peut pas dessiner ",
  },
  late: { en: "late", de: "überfällig", es: "vencidas", fr: "en retard" },
  noneAssignee: {
    en: "Unassigned",
    de: "Nicht zugewiesen",
    es: "Sin asignar",
    fr: "Non attribué",
  },
  noneProject: { en: "No project", de: "Kein Projekt", es: "Sin proyecto", fr: "Sans projet" },
  noneTag: { en: "Untagged", de: "Ohne Tag", es: "Sin etiqueta", fr: "Sans étiquette" },
  nonePriority: {
    en: "No priority",
    de: "Keine Priorität",
    es: "Sin prioridad",
    fr: "Sans priorité",
  },
  noneStatus: { en: "No status", de: "Kein Status", es: "Sin estado", fr: "Sans statut" },
  noneValue: { en: "Not set", de: "Nicht gesetzt", es: "Sin valor", fr: "Non renseigné" },
  categories: {
    backlog: { en: "Backlog", de: "Backlog", es: "Pendientes", fr: "Réserve" },
    todo: { en: "To do", de: "Zu erledigen", es: "Por hacer", fr: "À faire" },
    in_progress: { en: "In progress", de: "In Arbeit", es: "En curso", fr: "En cours" },
    done: { en: "Done", de: "Erledigt", es: "Hecho", fr: "Terminé" },
  },
  priorities: {
    urgent: { en: "Urgent", de: "Dringend", es: "Urgente", fr: "Urgent" },
    high: { en: "High", de: "Hoch", es: "Alta", fr: "Haute" },
    medium: { en: "Medium", de: "Mittel", es: "Media", fr: "Moyenne" },
    low: { en: "Low", de: "Niedrig", es: "Baja", fr: "Basse" },
  },
  booleans: {
    true: { en: "Yes", de: "Ja", es: "Sí", fr: "Oui" },
    false: { en: "No", de: "Nein", es: "No", fr: "Non" },
  },
};

/**
 * Built-in: board — tasks dealt into columns.
 *
 * Display only, like every widget on a dashboard: a card is a card, not a
 * handle. There is nothing to drag it onto and no affordance suggesting there
 * is, because moving work between states is a project view's job and a
 * dashboard only ever reads.
 *
 * What a column stands for is this widget's whole decision — a status, the
 * person on the work, a tag, or one of the initiative's own custom properties.
 * That last one is why the property arrives on the *binding* rather than as a
 * display option: options are a closed set of literals fixed at build time, and
 * a team's own field is by definition one this build never heard of. The host
 * resolves the binding to the property's name and the values it can take, so an
 * option nobody has used yet still gets its column instead of quietly ceasing
 * to exist.
 *
 * @param {import("../dataShapes").WidgetData} data
 * @param {import("../dataShapes").WidgetConfig} config
 */
function render(data, config, context) {
  // The viewer's language, and this module's own words in it. An older host
  // that passes no context leaves this at English rather than failing.
  const lang = context?.locale || "en";
  const resolve = (entry) => {
    const table = entry || {};
    return table[lang] || table[lang.split("-")[0]] || table.en;
  };
  const say = (key) => resolve(strings[key]) || key;
  const pick = (table, key) => resolve(table[key]) || key;

  const empty = (message) => ({ v: 1, scene: { kind: "empty", message } });

  if (data.source !== "tasks") return empty(say("cannotDraw") + data.source);

  const rows = data.rows || [];
  const group = config.group || "status";
  const sort = config.sort || "due";
  const detail = config.cards || "standard";
  const markOverdue = config.highlight !== "off";
  const columnOrder = config.columns || "natural";
  const property = data.property;

  // Grouping by a property nobody has pointed at is a binding that is not
  // finished, not an empty board — so say which half is missing.
  if (group === "property" && !property) return empty(say("needProperty"));
  if (!rows.length) return empty(say("noTasks"));

  // The clock the host handed us. A widget must never invent one.
  const today = Date.now();
  const CATEGORIES = ["backlog", "todo", "in_progress", "done"];
  const PRIORITIES = ["urgent", "high", "medium", "low"];

  /** The bucket for a task with nothing in the grouped field. Named for the
   *  field, because "Unassigned" and "Untagged" are not the same absence. */
  const noneLabel =
    group === "assignee"
      ? say("noneAssignee")
      : group === "project"
        ? say("noneProject")
        : group === "tag"
          ? say("noneTag")
          : group === "priority"
            ? say("nonePriority")
            : group === "status" || group === "status_category"
              ? say("noneStatus")
              : say("noneValue");

  /** How a raw field value reads. Statuses, project names and tags are already
   *  words somebody chose; the closed vocabularies are this module's to name. */
  const labelFor = (value) => {
    if (value === null) return noneLabel;
    if (group === "status_category") return pick(strings.categories, value);
    if (group === "priority") return pick(strings.priorities, value);
    if (group === "property" && (value === "true" || value === "false")) {
      return pick(strings.booleans, value);
    }
    return value;
  };

  /** The columns a task belongs in — several where the field holds several, so
   *  work shared by two people appears under both of them. */
  const keysFor = (task) => {
    switch (group) {
      case "assignee":
        return task.assignees.length ? task.assignees : [null];
      case "priority":
        return [task.priority || null];
      case "project":
        return [task.projectName || null];
      case "tag":
        return task.tags.length ? task.tags : [null];
      case "status_category":
        return [task.statusCategory || null];
      case "property": {
        const values = task.properties?.[property.name] || [];
        return values.length ? values : [null];
      }
      default:
        return [task.status || null];
    }
  };

  const isOverdue = (task) =>
    task.statusCategory !== "done" && task.dueDate !== null && task.dueDate < today;

  // --- the columns --------------------------------------------------------
  //
  // Keyed on the raw value, so two options that happen to read alike stay two
  // columns. Seeded from the declared values first: an option nobody has used
  // is still part of the workflow, and a column missing from a board is the one
  // thing a board must not hide.

  const columns = new Map();
  const columnFor = (key) => {
    const id = key === null ? " none" : key;
    let column = columns.get(id);
    if (!column) {
      column = { key: key, tasks: [], rank: columns.size };
      columns.set(id, column);
    }
    return column;
  };

  if (group === "property") {
    for (const value of property.values || []) columnFor(value);
  }
  // A category and a priority are fixed ladders, so every rung is drawn whether
  // or not any work is sitting on it.
  if (group === "status_category") for (const value of CATEGORIES) columnFor(value);
  if (group === "priority") for (const value of PRIORITIES) columnFor(value);

  for (const task of rows) {
    for (const key of keysFor(task)) columnFor(key).tasks.push(task);
  }

  // --- cards within a column ----------------------------------------------

  const priorityRank = (task) => {
    const index = PRIORITIES.indexOf(task.priority);
    return index === -1 ? PRIORITIES.length : index;
  };

  const compare = (a, b) => {
    switch (sort) {
      case "priority": {
        const byPriority = priorityRank(a) - priorityRank(b);
        if (byPriority !== 0) return byPriority;
        break;
      }
      case "created":
        if (a.createdAt !== b.createdAt) return b.createdAt - a.createdAt;
        break;
      case "updated":
        if (a.updatedAt !== b.updatedAt) return b.updatedAt - a.updatedAt;
        break;
      case "title": {
        const byTitle = a.title < b.title ? -1 : a.title > b.title ? 1 : 0;
        if (byTitle !== 0) return byTitle;
        break;
      }
      default: {
        // Undated work has no place on a due-date ladder, so it sits at the
        // foot rather than being given a date it does not have.
        const left = a.dueDate === null ? Infinity : a.dueDate;
        const right = b.dueDate === null ? Infinity : b.dueDate;
        if (left !== right) return left - right;
        break;
      }
    }
    // A stable tiebreak, so the same rows always draw in the same order.
    return a.id - b.id;
  };

  const cardFor = (task) => {
    const card = { title: task.title };
    if (markOverdue && isOverdue(task)) card.tone = "negative";
    if (detail === "compact") return card;

    const chips = [];
    // Never repeat the column's own field on the cards inside it: a column of
    // "Ada" whose every card says "Ada" is a column of wasted room.
    if (group !== "assignee") for (const name of task.assignees) chips.push(name);
    if (group !== "priority" && task.priority) chips.push(pick(strings.priorities, task.priority));
    if (detail === "detailed") {
      if (group !== "project" && task.projectName) chips.push(task.projectName);
      if (group !== "tag") for (const tag of task.tags) chips.push(tag);
    }
    if (chips.length) card.chips = chips;

    if (task.dueDate !== null) card.date = task.dueDate;
    if (task.subtaskTotal > 0) {
      card.caption = task.subtaskDone + "/" + task.subtaskTotal;
      card.progress = task.subtaskDone / task.subtaskTotal;
    }
    return card;
  };

  // --- column order -------------------------------------------------------

  const naturalRank = (column) => {
    // The empty bucket is nobody's first column, whatever the field.
    if (column.key === null) return Number.MAX_SAFE_INTEGER;
    if (group === "status_category") return CATEGORIES.indexOf(column.key);
    if (group === "priority") return PRIORITIES.indexOf(column.key);
    if (group === "property") return column.rank;
    if (group === "status") {
      // Statuses carry no order the rows can tell us, so they fall back to the
      // category ladder their work sits on — which is the order somebody
      // reading a board expects, even when the names are the initiative's own.
      const first = column.tasks[0];
      const category = first ? CATEGORIES.indexOf(first.statusCategory) : CATEGORIES.length;
      return (category === -1 ? CATEGORIES.length : category) * 1000 + column.rank;
    }
    return column.rank;
  };

  const labelled = [...columns.values()].map((column) => ({
    column: column,
    label: labelFor(column.key),
  }));

  const byLabel = (a, b) => (a.label < b.label ? -1 : a.label > b.label ? 1 : 0);

  if (columnOrder === "largest") {
    labelled.sort((a, b) => b.column.tasks.length - a.column.tasks.length);
  } else if (columnOrder === "label") {
    labelled.sort(byLabel);
  } else if (group === "assignee" || group === "project" || group === "tag") {
    // Free-form values have no ladder of their own, so alphabetical is the
    // order somebody can predict — with the empty bucket still last.
    labelled.sort((a, b) => {
      if ((a.column.key === null) !== (b.column.key === null)) {
        return a.column.key === null ? 1 : -1;
      }
      return byLabel(a, b);
    });
  } else {
    labelled.sort((a, b) => naturalRank(a.column) - naturalRank(b.column));
  }

  const scene = { kind: "board", columns: [] };
  for (const entry of labelled) {
    const tasks = entry.column.tasks.slice().sort(compare);
    const column = { label: entry.label, cards: tasks.map(cardFor) };
    if (markOverdue) {
      let late = 0;
      for (const task of tasks) if (isOverdue(task)) late++;
      if (late) column.caption = late + " " + say("late");
    }
    scene.columns.push(column);
  }

  return { v: 1, scene: scene };
}
