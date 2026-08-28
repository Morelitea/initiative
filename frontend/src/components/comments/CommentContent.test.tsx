import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { renderPage, renderWithProviders } from "@/__tests__/helpers/render";

import { CommentContent } from "./CommentContent";

const renderContent = (content: string) =>
  renderWithProviders(<CommentContent content={content} />);

/** Entity mentions render a router `Link`, so they need a mounted router. */
const renderLinkedContent = (content: string) =>
  renderPage(() => <CommentContent content={content} />);

describe("CommentContent", () => {
  it("renders markdown inline formatting", () => {
    const { container } = renderContent("Ship **now**, not *later*.");

    expect(container.querySelector("strong")).toHaveTextContent("now");
    expect(container.querySelector("em")).toHaveTextContent("later");
  });

  it("renders lists, headings, and code", () => {
    const { container } = renderContent(
      ["## Plan", "", "- first", "- second", "", "Run `pnpm test` first."].join("\n")
    );

    expect(screen.getByRole("heading", { level: 2 })).toHaveTextContent("Plan");
    expect(container.querySelectorAll("li")).toHaveLength(2);
    expect(container.querySelector("code")).toHaveTextContent("pnpm test");
  });

  it("renders fenced code blocks without interpreting their contents", () => {
    const { container } = renderContent(["```", "@[Ada](3) **not bold**", "```"].join("\n"));

    const code = container.querySelector("pre code");
    expect(code).toHaveTextContent("@[Ada](3) **not bold**");
    expect(container.querySelector("strong")).toBeNull();
  });

  it("renders GFM tables and strikethrough", () => {
    const { container } = renderContent(
      ["| a | b |", "| - | - |", "| 1 | 2 |", "", "~~dropped~~"].join("\n")
    );

    expect(container.querySelectorAll("th")).toHaveLength(2);
    expect(container.querySelector("del")).toHaveTextContent("dropped");
  });

  it("keeps single newlines as line breaks", () => {
    const { container } = renderContent("one\ntwo");

    expect(container.querySelectorAll("p")).toHaveLength(1);
    expect(container.querySelector("br")).not.toBeNull();
  });

  it("renders a user mention as a badge, not a link", () => {
    const { container } = renderContent("thanks @[Ada Lovelace](12)!");

    expect(screen.getByText("@Ada Lovelace")).toBeInTheDocument();
    expect(container.querySelector("a")).toBeNull();
  });

  it("links task, doc, and project mentions", async () => {
    renderLinkedContent("#task[Fix login](3) #doc[Runbook](4) #project[Apollo](5)");

    expect(await screen.findByRole("link", { name: /Fix login/ })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Runbook/ })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Apollo/ })).toBeInTheDocument();
  });

  it("keeps a mention rendered beside its surrounding markdown", async () => {
    const { container } = renderLinkedContent("**Heads up** @[Ada](12) — see #task[Fix login](3)");

    expect(await screen.findByRole("link", { name: /Fix login/ })).toBeInTheDocument();
    expect(container.querySelector("strong")).toHaveTextContent("Heads up");
    expect(screen.getByText("@Ada")).toBeInTheDocument();
  });

  it("leaves an ordinary numeric-target link alone", () => {
    renderContent("see [the docs](https://example.com/12)");

    const link = screen.getByRole("link", { name: "the docs" });
    expect(link).toHaveAttribute("href", "https://example.com/12");
  });

  it("autolinks bare urls and opens them in a new tab", () => {
    renderContent("docs at https://example.com/guide");

    const link = screen.getByRole("link", { name: /example\.com/ });
    expect(link).toHaveAttribute("href", "https://example.com/guide");
    expect(link).toHaveAttribute("target", "_blank");
    expect(link).toHaveAttribute("rel", expect.stringContaining("noopener"));
  });

  it("shows an image as a link instead of loading it", () => {
    const { container } = renderContent("![a diagram](https://example.com/pic.png)");

    expect(container.querySelector("img")).toBeNull();
    const link = screen.getByRole("link", { name: "a diagram" });
    expect(link).toHaveAttribute("href", "https://example.com/pic.png");
  });

  it("names an image by its address when it has no alt text", () => {
    renderContent("![](https://example.com/pic.png)");

    expect(screen.getByRole("link", { name: "https://example.com/pic.png" })).toBeInTheDocument();
  });

  it("does not render raw html", () => {
    const { container } = renderContent('<img src=x onerror="alert(1)"> <b>plain</b>');

    expect(container.querySelector("img")).toBeNull();
    expect(container.querySelector("b")).toBeNull();
  });
});
