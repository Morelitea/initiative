import { screen } from "@testing-library/react";

import { buildTask } from "@/__tests__/factories";
import { renderPage } from "@/__tests__/helpers/render";
import type { TaskListRead } from "@/api/generated/initiativeAPI.schemas";

import { compileTemplate } from "./compile";
import { MAX_RENDERED_NODES, renderTemplate } from "./render";
import { defineSection } from "./sections";

const section = defineSection<{ task: TaskListRead }>()({
  data: { task: "TaskListRead" },
  parts: { title: { required: true } },
});

const draw = (source: string, task: TaskListRead) => {
  const { template, errors } = compileTemplate(source, { name: "test.card", section });
  expect(errors).toEqual([]);
  const Title = ({ data }: { data: { task: TaskListRead } }) => <h2>{data.task.title}</h2>;
  const Page = () => (
    <>
      {renderTemplate(template as NonNullable<typeof template>, {
        data: { task },
        context: undefined,
        parts: { title: Title as never },
        communityId: 7,
      })}
    </>
  );
  return renderPage(Page);
};

describe("renderTemplate", () => {
  it("draws text, branches, lists, classes and parts from the section's data", async () => {
    const task = buildTask({ title: "Ship it", priority: "high" });
    draw(
      `<article data-testid="card" class="card" :class="{ 'card--high': task.priority == 'high' }">
         <part name="title" class="card__title" />
         <span if="task.priority == 'urgent'">Urgent</span>
         <span else-if="task.priority == 'high'">High</span>
         <span else>Calm</span>
         <p>{{ task.title.upperAscii() }} has {{ size(task.title) }} letters</p>
         <ul><li for="word in task.title.split(' ')">{{ word }}</li></ul>
       </article>`,
      task
    );

    const card = await screen.findByTestId("card");
    expect(card).toHaveClass("card", "card--high");
    expect(screen.getByRole("heading", { name: "Ship it" }).parentElement).toHaveAttribute(
      "data-part",
      "title"
    );
    expect(screen.getByText("High")).toBeInTheDocument();
    expect(screen.queryByText("Calm")).not.toBeInTheDocument();
    expect(screen.getByText("SHIP IT has 7 letters")).toBeInTheDocument();
    expect(screen.getAllByRole("listitem").map((item) => item.textContent)).toEqual(["Ship", "it"]);
  });

  it("holds links, pictures and CSS values to what they may be", async () => {
    draw(
      `<part name="title" />
       <a href="/c/7/i/1/projects/2">Inside</a>
       <a href="https://example.com">Outside</a>
       <a :href="'/c/8/i/1'">Another community</a>
       <img data-testid="ours" src="/uploads/7/a.png" alt="ours" />
       <img src="https://example.com/a.png" alt="theirs" />
       <img src="/uploads/7/../8/a.png" alt="dotted" />
       <img src="/uploads/7/%2e%2e/8/a.png" alt="encoded" />
       <a href="/c/7/../8/i/1">Climbs out</a>
       <span data-testid="hidden" :aria-hidden="true">x</span>
       <div data-testid="styled" :style="{ '--gap': 4, '--ok': '#fff', '--bad': 'url(https://x)', 'color': 'red' }"></div>`,
      buildTask()
    );

    expect(await screen.findByRole("link", { name: "Inside" })).toHaveAttribute(
      "href",
      "/c/7/i/1/projects/2"
    );
    expect(screen.queryByRole("link", { name: "Outside" })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Another community" })).not.toBeInTheDocument();
    expect(screen.getByText("Outside").tagName).toBe("SPAN");
    expect(screen.getByTestId("ours")).toHaveAttribute("src", "/uploads/7/a.png");
    expect(screen.queryByAltText("theirs")).not.toBeInTheDocument();
    const styled = screen.getByTestId("styled");
    expect(styled.style.getPropertyValue("--gap")).toBe("4");
    expect(styled.style.getPropertyValue("--ok")).toBe("#fff");
    expect(styled.style.getPropertyValue("--bad")).toBe("");
    expect(styled.style.color).toBe("");
    expect(screen.queryByAltText("dotted")).not.toBeInTheDocument();
    expect(screen.queryByAltText("encoded")).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Climbs out" })).not.toBeInTheDocument();
    expect(screen.getByTestId("hidden")).toHaveAttribute("aria-hidden", "true");
  });

  it("stops drawing at its budget, however long the list", async () => {
    draw(
      `<part name="title" /><ul><li for="word in task.title.split(' ')">{{ word }}</li></ul>`,
      buildTask({ title: "x ".repeat(MAX_RENDERED_NODES) })
    );
    await screen.findByRole("list");
    expect(screen.getAllByRole("listitem").length).toBeLessThan(MAX_RENDERED_NODES);
  });
});
