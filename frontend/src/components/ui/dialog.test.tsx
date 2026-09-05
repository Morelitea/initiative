/**
 * A dialog fits the phone it is opened on.
 *
 * Two rules, both of which were broken and both of which are invisible until
 * somebody opens a dialog on a narrow screen:
 *
 * 1. The content box is a grid, so its children are grid items with
 *    `min-width: auto` — a nowrap row or an editor toolbar sets a content
 *    minimum wider than the dialog and spills out of it rather than shrinking.
 * 2. A caller that sets an unprefixed `max-w-*` replaces the base viewport cap
 *    at *every* width, so the dialog loses its margins on mobile. Widths belong
 *    behind `sm:`, where the base `max-w-[calc(100%-2rem)]` still governs
 *    below it.
 *
 * These are asserted against the classes rather than a layout, because jsdom
 * does no layout — which is exactly why neither was caught by the suite.
 */
import fs from "node:fs";
import path from "node:path";

import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { Dialog, DialogContent, DialogTitle } from "./dialog";

const SRC = path.resolve(__dirname, "../..");

describe("DialogContent", () => {
  it("lets its grid children shrink instead of overflowing", () => {
    render(
      <Dialog open>
        <DialogContent>
          <DialogTitle>Anything</DialogTitle>
        </DialogContent>
      </Dialog>
    );

    const content = screen.getByRole("dialog");
    expect(content.className).toContain("[&>*]:min-w-0");
  });

  it("keeps the viewport cap when a caller sets its own width", () => {
    render(
      <Dialog open>
        <DialogContent className="sm:max-w-2xl">
          <DialogTitle>Anything</DialogTitle>
        </DialogContent>
      </Dialog>
    );

    const content = screen.getByRole("dialog");
    // Both survive: the base governs below `sm`, the caller's above it.
    expect(content.className).toContain("max-w-[calc(100%-2rem)]");
    expect(content.className).toContain("sm:max-w-2xl");
  });

  // The class-merge rule the case above relies on, enforced across the app: an
  // unprefixed width silently drops the base cap, and every dialog that did
  // that was edge-to-edge on a phone.
  it("no dialog sets an unprefixed max width", () => {
    const offenders: string[] = [];
    const walk = (dir: string) => {
      for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
        const full = path.join(dir, entry.name);
        if (entry.isDirectory()) {
          walk(full);
        } else if (entry.name.endsWith(".tsx")) {
          const source = fs.readFileSync(full, "utf-8");
          for (const match of source.matchAll(/<DialogContent\s+className="([^"]*)"/g)) {
            if (/(?:^|\s)max-w-(?:xs|sm|md|lg|xl|\dxl)(?:\s|$)/.test(match[1])) {
              offenders.push(`${path.relative(SRC, full)}: ${match[1]}`);
            }
          }
        }
      }
    };
    walk(SRC);

    expect(offenders, `put these behind sm: — ${offenders.join(", ")}`).toEqual([]);
  });
});
