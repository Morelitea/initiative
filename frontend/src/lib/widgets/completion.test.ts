import { describe, expect, it } from "vitest";

import {
  applyCompletion,
  completionsFor,
  type DatasetFields,
  datasetsNamed,
  wordAt,
} from "@/lib/widgets/completion";

const DATASETS = ["tasks", "projects", "calendar_events"];
const FUNCTIONS = ["count", "date_trunc", "lower"];
const FIELDS: DatasetFields[] = [
  {
    dataset: "tasks",
    fields: [
      { name: "title", type: "text" },
      { name: "due_date", type: "date" },
      { name: "priority", type: "enum" },
    ],
  },
  {
    dataset: "projects",
    fields: [
      { name: "name", type: "text" },
      { name: "start_date", type: "date" },
    ],
  },
];

const vocabulary = { datasets: DATASETS, functions: FUNCTIONS, fields: FIELDS };

describe("the word being typed", () => {
  it("is what precedes the caret", () => {
    expect(wordAt("SELECT ti", 9)).toEqual({ word: "ti", start: 7 });
  });

  it("is nothing where a name could not go", () => {
    expect(wordAt("SELECT ", 7)).toBeNull();
    expect(wordAt("", 0)).toBeNull();
  });

  it("is nothing from inside a word", () => {
    // Completing here would replace only the left half of `title`.
    expect(wordAt("SELECT title", 9)).toBeNull();
  });

  it("stops at what a name cannot contain", () => {
    expect(wordAt("WHERE t.pri", 11)).toEqual({ word: "pri", start: 8 });
    expect(wordAt("count(ti", 8)).toEqual({ word: "ti", start: 6 });
  });
});

describe("what is offered", () => {
  it("is nothing until something is typed", () => {
    expect(completionsFor("", vocabulary)).toEqual([]);
  });

  it("leads with what starts with the word", () => {
    const names = completionsFor("da", vocabulary).map((entry) => entry.name);
    // `date_trunc` starts with it; `due_date` and `start_date` only contain it.
    expect(names[0]).toBe("date_trunc");
    expect(names).toContain("due_date");
    expect(names.indexOf("date_trunc")).toBeLessThan(names.indexOf("due_date"));
  });

  it("offers datasets, fields and functions together", () => {
    const kinds = new Set(completionsFor("t", vocabulary).map((entry) => entry.kind));
    expect(kinds).toEqual(new Set(["dataset", "field", "function"]));
  });

  it("offers the reader beside them", () => {
    const found = completionsFor("m", { ...vocabulary, tokens: ["me"] });
    expect(found).toContainEqual({ name: "me", kind: "token" });
  });

  it("offers no token where the server names none", () => {
    const kinds = completionsFor("m", vocabulary).map((entry) => entry.kind);
    expect(kinds).not.toContain("token");
  });

  it("says where a field comes from", () => {
    const found = completionsFor("priority", vocabulary)[0];
    expect(found).toBeUndefined();
    const partial = completionsFor("prior", vocabulary)[0];
    expect(partial).toMatchObject({ name: "priority", kind: "field", detail: "tasks · enum" });
  });

  it("does not offer the word already written in full", () => {
    expect(completionsFor("tasks", vocabulary).map((entry) => entry.name)).not.toContain("tasks");
  });

  it("is case-insensitive", () => {
    expect(completionsFor("TI", vocabulary).map((entry) => entry.name)).toContain("title");
  });

  it("offers the same field once per dataset that has it", () => {
    const shared: DatasetFields[] = [
      { dataset: "tasks", fields: [{ name: "created_at", type: "date" }] },
      { dataset: "projects", fields: [{ name: "created_at", type: "date" }] },
    ];
    const found = completionsFor("created", { ...vocabulary, fields: shared });
    expect(found).toHaveLength(2);
    expect(found.map((entry) => entry.detail)).toEqual(["tasks · date", "projects · date"]);
  });
});

describe("the datasets a statement names", () => {
  it("are the ones written as whole words", () => {
    expect(datasetsNamed("SELECT title FROM tasks", DATASETS)).toEqual(["tasks"]);
  });

  it("do not include one that is only a prefix of a word", () => {
    expect(datasetsNamed("SELECT task_status_id FROM x", DATASETS)).toEqual([]);
  });

  it("include every one a join names", () => {
    expect(
      datasetsNamed("SELECT p.name FROM projects p JOIN tasks t ON t.project_id = p.id", DATASETS)
    ).toEqual(["tasks", "projects"]);
  });
});

describe("accepting one", () => {
  it("replaces the word being typed", () => {
    expect(applyCompletion("SELECT ti", 7, 9, { name: "title", kind: "field" })).toEqual({
      text: "SELECT title",
      caret: 12,
    });
  });

  it("opens the bracket on a function", () => {
    expect(applyCompletion("SELECT co", 7, 9, { name: "count", kind: "function" })).toEqual({
      text: "SELECT count(",
      caret: 13,
    });
  });

  it("keeps what follows the caret", () => {
    expect(applyCompletion("SELECT ti FROM tasks", 7, 9, { name: "title", kind: "field" })).toEqual(
      { text: "SELECT title FROM tasks", caret: 12 }
    );
  });
});
