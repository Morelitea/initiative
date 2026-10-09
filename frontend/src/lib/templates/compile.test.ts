import { compileTemplate } from "./compile";
import { checkExpression, MAX_EXPRESSION_LENGTH } from "./expressions";
import { parseTemplate } from "./parse";
import { SECTIONS } from "./sections";

const compile = (source: string) =>
  compileTemplate(source, { name: "task.card", section: SECTIONS["task.card"] });
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
    expect(() => parseTemplate("<p>&#1114112;</p>")).toThrow(/is not a character.*line 1/);
  });

  it("reads an expression to its own closing braces, past strings and maps", () => {
    const [p] = parseTemplate(`<p>{{ '}}' }} {{ {'a': {'b': 1}}.a.b }}</p>`);
    expect(p?.kind === "element" && p.children[0]).toMatchObject({
      parts: [{ expression: "'}}'" }, " ", { expression: "{'a': {'b': 1}}.a.b" }],
    });
  });

  it("keeps a space within a line and drops whitespace that breaks one", () => {
    const [p] = parseTemplate("<p>\n  <span>Due</span> <strong>today</strong>&nbsp;\n</p>");
    expect(p?.kind === "element" && p.children.map((child) => child.kind)).toEqual([
      "element",
      "text",
      "element",
      "text",
    ]);
    expect(p?.kind === "element" && p.children[1]).toMatchObject({ parts: [" "] });
    expect(p?.kind === "element" && p.children[3]).toMatchObject({ parts: ["\u00a0 "] });
  });
});

describe("checkExpression", () => {
  const scope = new Map([["task", { ref: "TaskListRead" } as const]]);
  const check = (source: string) => checkExpression(source, scope);

  it("checks names, fields and functions against what the section reads", () => {
    expect(check("task.title.lowerAscii() == 'x'").problems).toEqual([]);
    expect(check("has(task.due_date)").problems).toEqual([]);
    expect(check("task.nope").problems).toEqual(["There is no field nope here"]);
    expect(check("project.name").problems).toEqual(["Nothing is called project here"]);
    expect(check("fetch(task.title)").problems).toEqual([
      "fetch() is not a function templates may use",
    ]);
    expect(check("task.title ==").problems[0]).toMatch(/^Does not parse/);
    // A map's keys are expressions too: an unquoted one is a name, and checked as one.
    expect(check("{ color: 1 }").problems).toEqual(["Nothing is called color here"]);
    // What a list holds survives indexing and filtering, so its fields are still checked.
    expect(check("task.assignees[0].nope").problems).toEqual(["There is no field nope here"]);
    expect(check("task.assignees.filter(a, true).exists(b, b.nope)").problems).toEqual([
      "There is no field nope here",
    ]);
  });

  it("holds comprehension nesting, node count and length to their limits", () => {
    const list = "task.assignees";
    expect(check(`${list}.map(a, ${list}.filter(b, b.id == a.id))`).problems).toEqual([]);
    expect(
      check(`${list}.map(a, ${list}.map(b, ${list}.filter(c, c.id == b.id)))`).problems
    ).toEqual(["map, filter, all and exists nest at most 2 deep"]);
    expect(check(`${"1+".repeat(110)}1`).problems).toEqual(["Expressions are at most 200 parts"]);
    expect(check("x".repeat(MAX_EXPRESSION_LENGTH + 1)).problems).toEqual([
      `Expressions are at most ${MAX_EXPRESSION_LENGTH} characters long`,
    ]);
    // A comprehension's variable holds one item of the list, so its fields are checked too.
    expect(check(`${list}.exists(a, a.nope)`).problems).toEqual(["There is no field nope here"]);
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
    // None calls a display function, so the renderer may reuse every answer.
    expect(template?.display).toEqual([]);
    expect(
      compile(`<part name="title" /><p>{{ task.title }} {{ format_date(task.created_at) }}</p>`)
        .template?.display
    ).toEqual([1]);
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
      "task.card must place its title part (line 1, column 1)",
    ]);
    expect(errorsOf(`<part name="title" /><part name="title" />`)[0]).toMatch(
      /title is placed 2 times/
    );
    expect(errorsOf(`<div if="true"><part name="title" /></div>`)[0]).toMatch(
      /title is required, so it cannot sit inside if or for/
    );
    expect(errorsOf(`<part name="title" /><part name="relations" />`)[0]).toMatch(
      /task.card has no part called relations/
    );
    // An optional part may come and go.
    expect(
      errorsOf(`<part name="title" /><part if="has(task.due_date)" name="description" />`)
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
    expect(
      errorsOf(`<part name="title" />
        <ul for="a in task.assignees"><li for="b in task.assignees"><span for="c in task.assignees"></span></li></ul>`)[0]
    ).toMatch(/for nests at most 2 deep/);
    // A space between an if and its else, on one line, belongs to neither branch.
    expect(errorsOf(`<part name="title" /><strong if="true">a</strong> <em else>b</em>`)).toEqual(
      []
    );
    // A comment between them does not split the space in two.
    expect(
      errorsOf(`<part name="title" /><strong if="true">a</strong> <!-- note --> <em else>b</em>`)
    ).toEqual([]);
    // After a chain ends, a space is a space again.
    const { template } = compile(
      `<p><part name="title" /><strong if="true">Due</strong> <em>today</em></p>`
    );
    const p = template?.root[0];
    expect(p?.t === "el" && p.kids.map((kid) => kid.t)).toEqual(["part", "if", "text", "el"]);
  });
});
