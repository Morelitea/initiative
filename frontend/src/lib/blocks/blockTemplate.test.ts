import { compileBlock } from "./blockTemplate";

const errorsOf = (source: string) =>
  compileBlock(
    source,
    [
      { key: "task_id", type: "int", list: true },
      { key: "running_since", type: "datetime", list: true },
    ],
    ["start"],
    ["timers.start", "timers.stop"],
    ["timesheet"]
  ).errors.map((error) => error.message);

describe("compileBlock", () => {
  it("compiles a block that reads its task, its row and its words, with its elements", () => {
    const { template, errors } = compileBlock(
      `<span class="flex gap-1" if="answer != null && answer.running_since != null">
         <timer :since="answer.running_since" /><button action="timers.stop">{{ task.title }}</button>
       </span>
       <button else action="timers.start">{{ strings.start }}</button>
       <open page="timesheet">{{ area }} {{ width }}</open><copy :value="string(now)" />`,
      [{ key: "running_since", type: "datetime", list: true }],
      ["start"],
      ["timers.start", "timers.stop"],
      ["timesheet"]
    );
    expect(errors).toEqual([]);
    const button = template?.root.find((node) => node.t === "if");
    expect(button?.t === "if" && button.branches[1]?.node).toMatchObject({
      t: "component",
      name: "button",
      attrs: { action: "timers.start" },
      kids: [{ t: "text" }],
    });
  });

  it("names only declared actions and pages, as written", () => {
    expect(errorsOf(`<button action="timers.reset">Reset</button>`)[0]).toMatch(
      /<button> names action timers.reset, which is not declared/
    );
    expect(errorsOf(`<button :action="strings.start">Go</button>`)[0]).toMatch(
      /<button> needs action, given as it is/
    );
    expect(errorsOf(`<open page="settings">Open</open>`)[0]).toMatch(
      /<open> names page settings, which is not declared/
    );
    expect(errorsOf(`<timer :since="answer.running_since">1</timer>`)[0]).toMatch(
      /<timer> holds nothing/
    );
  });

  it("holds a block to the plug-in vocabulary", () => {
    expect(errorsOf(`<input />`)[0]).toMatch(/<input> is not an element templates may use/);
    expect(errorsOf(`<span class="bg-red-500">x</span>`)[0]).toMatch(/The class bg-red-500/);
    expect(errorsOf(`<span>{{ answer.missing }}</span>`)).not.toEqual([]);
    expect(errorsOf(`<blocks area="inline" />`)[0]).toMatch(/cannot place <blocks>/);
  });
});
