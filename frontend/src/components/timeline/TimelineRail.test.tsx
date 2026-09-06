/**
 * The reusable timeline rail.
 *
 * Written against the generic contract rather than any tool's shape, because
 * that is the thing being kept: a rail that only worked for posts would have to
 * be rewritten for the next tool that wants one.
 *
 * What is load-bearing is that it is a *list of buttons* with dragging layered
 * on top, not a drag surface with buttons bolted beside it — that is what makes
 * it reachable by keyboard and readable by a screen reader, and what makes the
 * same control work on a phone.
 */
import fs from "node:fs";
import path from "node:path";

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { TimelineRail, type TimelineStop } from "./TimelineRail";

const stops = [
  { period: "2026-03", count: 9 },
  { period: "2026-01", count: 1 },
  { period: "2025-12", count: 4 },
];

const label = (stop: TimelineStop) => `Month ${stop.period}`;
const group = (stop: TimelineStop) => stop.period.slice(0, 4);

const renderRail = (props: Partial<Parameters<typeof TimelineRail>[0]> = {}) =>
  render(
    <TimelineRail
      stops={stops}
      onPick={vi.fn()}
      formatLabel={label}
      formatGroup={group}
      {...props}
    />
  );

describe("TimelineRail", () => {
  it("offers every period as its own button", () => {
    renderRail();

    for (const stop of stops) {
      expect(screen.getByRole("button", { name: label(stop) })).toBeInTheDocument();
    }
  });

  it("hands back the whole stop, not just its period", async () => {
    const onPick = vi.fn();
    renderRail({ onPick });

    await userEvent.click(screen.getByRole("button", { name: "Month 2025-12" }));

    expect(onPick).toHaveBeenCalledWith(stops[2]);
  });

  it("labels a year once, where it changes", () => {
    renderRail();

    // Three stops across two years: 2026 is labelled at the first of its two,
    // not at both, so the rail reads as a run of months under a year.
    expect(screen.getAllByText("2026")).toHaveLength(1);
    expect(screen.getAllByText("2025")).toHaveLength(1);
  });

  it("marks where the feed actually is", () => {
    renderRail({ activePeriod: "2026-01" });

    expect(screen.getByRole("button", { name: "Month 2026-01" })).toHaveAttribute(
      "aria-current",
      "true"
    );
    expect(screen.getByRole("button", { name: "Month 2026-03" })).not.toHaveAttribute(
      "aria-current"
    );
  });

  it("draws nothing at all when there is nowhere to jump", () => {
    const { container } = renderRail({ stops: [] });

    expect(container).toBeEmptyDOMElement();
  });

  // A tick's length is its share of the busiest period. Without it a year of
  // quiet months and one loud one look identical, and the rail stops being a
  // picture of the feed.
  it("draws a busy period longer than a quiet one", () => {
    const { container } = renderRail();
    const widths = [...container.querySelectorAll<HTMLElement>("button > span")].map((tick) =>
      Number.parseInt(tick.style.width, 10)
    );

    expect(widths[0]).toBeGreaterThan(widths[2]);
    expect(widths[2]).toBeGreaterThan(widths[1]);
  });

  it("keeps the quietest period big enough to hit", () => {
    const { container } = renderRail({
      stops: [
        { period: "2026-03", count: 500 },
        { period: "2026-02", count: 1 },
      ],
    });
    const ticks = [...container.querySelectorAll<HTMLElement>("button > span")];

    expect(Number.parseInt(ticks[1].style.width, 10)).toBeGreaterThanOrEqual(30);
  });

  // The rail lives beside a feed somebody is reading. Anything drawn outside
  // its own width lands on that feed — which is exactly what a year label
  // positioned `right-full` did. The one deliberate exception is the drag
  // bubble, a transient readout that is meant to float clear of the rail.
  // The rail is a drag surface with real buttons inside it. A tap on a button
  // fires the button's own click AND bubbles through the rail's pointerup, so
  // without a guard one activation runs a consumer's callback twice — harmless
  // for a board that just scrolls, not for whatever reuses this next.
  it("picks once for one tap on a stop", async () => {
    const onPick = vi.fn();
    renderRail({ onPick });

    await userEvent.click(screen.getByRole("button", { name: "Month 2026-03" }));

    expect(onPick).toHaveBeenCalledTimes(1);
  });

  it("keeps its labels inside its own width", () => {
    const source = fs
      .readFileSync(path.resolve(__dirname, "./TimelineRail.tsx"), "utf-8")
      // Comments explain the rule; only the classes actually applied count.
      .replace(/\/\*[\s\S]*?\*\//g, "")
      .replace(/\/\/.*$/gm, "");
    const escapes = [...source.matchAll(/(right-full|left-full)/g)];
    const bubble = [...source.matchAll(/role="status"[\s\S]{0,400}?(right-full|left-full)/g)];

    expect(escapes).toHaveLength(bubble.length);
  });
});
