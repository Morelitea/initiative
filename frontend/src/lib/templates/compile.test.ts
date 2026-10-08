import type { TaskRead } from "@/api/generated/initiativeAPI.schemas";

import { compileTemplate } from "./compile";
import { checkExpression, MAX_EXPRESSION_LENGTH } from "./expressions";
import { parseTemplate } from "./parse";
import { defineSection } from "./sections";
import { schemaShape } from "./shapes";

const section = defineSection<{ task: TaskRead }>()({
  data: { task: "TaskRead" },
  parts: { title: { required: true }, checklist: {} },
});

const compile = (source: string) => compileTemplate(source, { name: "test.card", section });
const errorsOf = (source: string) => compile(source).errors.map((error) => error.message);

describe("parseTemplate", () => {
  it("reads elements, attributes, text and expressions, and places what it refuses", () => {
    const [root] = parseTemplate(
      `<article class="card" :title="task.title">\n  Due {{ task.due_date }} &amp; <hr></article>`
    );
    expect(root).toMatchObject({
      kind: "element",
      name: "article",
      attributes: [
        { name: "class", value: "card" },
        { name: ":title", value: "task.title" },
      ],
      children: [
        { kind: "text", parts: [" Due ", { expression: "task.due_date" }, " & "] },
        { kind: "element", name: "hr", children: [] },
      ],
    });

    expect(() => parseTemplate("<div>\n  <span>")).toThrow(/<span> is never closed/);
    expect(() => parseTemplate("<div class=card></div>")).toThrow(/must be quoted.*line 1/);
    expect(() => parseTemplate("<div>\n</span>")).toThrow(
      /<\/span> closes <div>.*line 2, column 1/
    );
    expect(() => parseTemplate("<p>{{ task.title</p>")).toThrow(/Unclosed \{\{/);
  });
});

describe("checkExpression", () => {
  const scope = new Map([["task", schemaShape("TaskRead") ?? "any"]]);

  it("checks names, fields and functions against what the section reads", () => {
    expect(checkExpression("task.title.lowerAscii() == 'x'", scope).problems).toEqual([]);
    expect(checkExpression("has(task.due_date)", scope).problems).toEqual([]);
    expect(checkExpression("task.nope", scope).problems).toEqual(["There is no field nope here"]);
    expect(checkExpression("project.name", scope).problems).toEqual([
      "Nothing is called project here",
    ]);
    expect(checkExpression("fetch(task.title)", scope).problems).toEqual([
      "fetch() is not a function templates may use",
    ]);
    expect(checkExpression("task.title ==", scope).problems[0]).toMatch(/^Does not parse/);
    // A map's keys are expressions too: an unquoted one is a name, and checked as one.
    expect(checkExpression("{ color: 1 }", scope).problems).toEqual([
      "Nothing is called color here",
    ]);
  });

  it("holds comprehension nesting, node count and length to their limits", () => {
    const list = "task.assignees";
    expect(
      checkExpression(`${list}.map(a, ${list}.filter(b, b.id == a.id))`, scope).problems
    ).toEqual([]);
    expect(
      checkExpression(`${list}.map(a, ${list}.map(b, ${list}.filter(c, c.id == b.id)))`, scope)
        .problems
    ).toEqual(["map, filter, all and exists nest at most 2 deep"]);
    expect(checkExpression(`${"1+".repeat(110)}1`, scope).problems).toEqual([
      "Expressions are at most 200 parts",
    ]);
    expect(checkExpression("x".repeat(MAX_EXPRESSION_LENGTH + 1), scope).problems).toEqual([
      `Expressions are at most ${MAX_EXPRESSION_LENGTH} characters long`,
    ]);
    // A comprehension's variable holds one item of the list, so its fields are checked too.
    expect(checkExpression(`${list}.exists(a, a.nope)`, scope).problems).toEqual([
      "There is no field nope here",
    ]);
  });
});

describe("compileTemplate", () => {
  it("compiles structure, directives and parts into the renderer's tree", () => {
    const { template, errors } = compile(`
      <article class="card">
        <part name="title" />
        <span if="task.priority == 'urgent'">Urgent</span>
        <span else-if="task.priority == 'high'">High</span>
        <span else>{{ task.priority }}</span>
        <ul><li for="a in task.assignees">{{ a.display_name }}</li></ul>
        <p :class="{ 'done': task.task_status.category == 'done' }">{{ task.priority }}</p>
      </article>`);
    expect(errors).toEqual([]);
    expect(template?.exprs).toEqual([
      "task.priority == 'urgent'",
      "task.priority == 'high'",
      "task.priority",
      "task.assignees",
      "a.display_name",
      "{ 'done': task.task_status.category == 'done' }",
    ]);
    const article = template?.root[0];
    expect(article).toMatchObject({ t: "el", tag: "article", attrs: { class: "card" } });
    expect(article?.t === "el" && article.kids.map((kid) => kid.t)).toEqual([
      "part",
      "if",
      "el",
      "el",
    ]);
  });

  it("allows only the elements and attributes on its lists", () => {
    expect(errorsOf(`<part name="title" /><script></script>`)).toEqual([
      "<script> is not an element templates may use (line 1, column 22)",
    ]);
    expect(errorsOf(`<part name="title" /><div onclick="x"></div>`)[0]).toMatch(
      /<div> cannot have onclick/
    );
    expect(errorsOf(`<part name="title" /><div style="color: red"></div>`)[0]).toMatch(
      /Use :style/
    );
    expect(errorsOf(`<part name="title" /><div data-part="x"></div>`)[0]).toMatch(
      /data-part is Initiative's own/
    );
    expect(errorsOf(`<part name="title" /><a :target="'_blank'"></a>`)[0]).toMatch(
      /<a> cannot have :target/
    );
  });

  it("places every required part exactly once, never conditionally", () => {
    expect(errorsOf("<div></div>")).toEqual([
      "test.card must place its title part (line 1, column 1)",
    ]);
    expect(errorsOf(`<part name="title" /><part name="title" />`)[0]).toMatch(
      /title is placed 2 times/
    );
    expect(errorsOf(`<div if="true"><part name="title" /></div>`)[0]).toMatch(
      /title is required, so it cannot sit inside if or for/
    );
    expect(errorsOf(`<part name="title" /><part name="comments" />`)[0]).toMatch(
      /test.card has no part called comments/
    );
    // An optional part may come and go.
    expect(
      errorsOf(`<part name="title" /><part if="has(task.due_date)" name="checklist" />`)
    ).toEqual([]);
  });

  it("refuses directives that do not make sense together", () => {
    expect(errorsOf(`<part name="title" /><span else>x</span>`)[0]).toMatch(
      /else must follow an if/
    );
    expect(
      errorsOf(`<part name="title" /><li for="a in task.assignees" if="true"></li>`)[0]
    ).toMatch(/for and if on one element are ambiguous/);
    expect(errorsOf(`<part name="title" /><li for="task.assignees"></li>`)[0]).toMatch(
      /for reads "item in list"/
    );
  });
});
