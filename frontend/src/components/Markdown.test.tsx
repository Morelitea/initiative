import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { Markdown } from "./Markdown";

/** The wrapper the classes that keep content inside its container live on. */
const root = (container: HTMLElement) => container.firstElementChild as HTMLElement;

describe("Markdown", () => {
  it("renders nothing for empty content", () => {
    const { container } = render(<Markdown content="" />);
    expect(container).toBeEmptyDOMElement();
  });

  it("wraps code fences instead of letting them widen the container", () => {
    const { container } = render(
      <Markdown content={"```\nconst averyveryverylongidentifierwithnospaces = 1;\n```"} />
    );

    const classes = root(container).className;
    expect(classes).toContain("[&_pre]:whitespace-pre-wrap");
    expect(classes).toContain("[&_pre]:wrap-break-word");
    expect(classes).toContain("[&_pre]:max-w-full");
    expect(classes).toContain("[&_pre]:overflow-x-auto");
    expect(container.querySelector("pre")).not.toBeNull();
  });

  it("breaks long inline code, links and prose", () => {
    const { container } = render(<Markdown content="`inline` and text" />);

    const classes = root(container).className;
    expect(classes).toContain("wrap-break-word");
    expect(classes).toContain("[&_code]:wrap-break-word");
    expect(classes).toContain("[&_a]:break-all");
    expect(classes).toContain("[&_img]:max-w-full");
  });

  it("scrolls a wide table instead of widening the container", () => {
    const { container } = render(<Markdown content={"| a | b |\n| - | - |\n| 1 | 2 |"} />);

    const classes = root(container).className;
    expect(classes).toContain("[&_table]:overflow-x-auto");
    expect(classes).toContain("[&_table]:max-w-full");
    expect(container.querySelector("table")).not.toBeNull();
  });

  it("keeps the caller's classes alongside the defaults", () => {
    const { container } = render(<Markdown content="hello" className="line-clamp-2" />);

    expect(root(container).className).toContain("line-clamp-2");
    expect(screen.getByText("hello")).toBeInTheDocument();
  });

  it("does not leak the hast node onto rendered elements", () => {
    const { container } = render(<Markdown content="[link](https://example.com)" />);

    const anchor = container.querySelector("a");
    expect(anchor?.getAttribute("node")).toBeNull();
  });

  it("opens a picture full size, paging through the others in reading order", async () => {
    const user = userEvent.setup();
    render(<Markdown content={"![First](/a.png)\n\ntext\n\n![Second](/b.png)"} />);

    await user.click(screen.getByRole("button", { name: "View Second full size" }));

    const dialog = screen.getByRole("dialog");
    expect(within(dialog).getByRole("img", { name: "Second" })).toBeInTheDocument();
    expect(within(dialog).getByText("2 / 2")).toBeInTheDocument();
  });

  it("leaves a picture inside a link to the link", () => {
    render(<Markdown content="[![Badge](/badge.svg)](https://example.com)" />);

    expect(screen.queryByRole("button")).not.toBeInTheDocument();
    expect(screen.getByRole("link").querySelector("img")).not.toBeNull();
  });

  it("draws the picture without a way to open it when zooming is off", () => {
    render(<Markdown content="![Shot](/a.png)" zoomImages={false} />);

    expect(screen.queryByRole("button")).not.toBeInTheDocument();
    expect(screen.getByRole("img", { name: "Shot" })).toBeInTheDocument();
  });
});
