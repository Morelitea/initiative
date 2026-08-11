import { render, screen } from "@testing-library/react";
import { StrictMode } from "react";
import GridLayout from "react-grid-layout";
import { describe, expect, it, vi } from "vitest";

// Temporary Phase-2 gate check: RGL v2 under React 19 + StrictMode.
describe("react-grid-layout v2 on React 19", () => {
  it("renders children in StrictMode without findDOMNode warnings", () => {
    const errors: unknown[][] = [];
    const spy = vi.spyOn(console, "error").mockImplementation((...args) => void errors.push(args));

    render(
      <StrictMode>
        <GridLayout
          cols={12}
          rowHeight={40}
          width={1200}
          layout={[
            { i: "a", x: 0, y: 0, w: 6, h: 3 },
            { i: "b", x: 6, y: 0, w: 6, h: 3 },
          ]}
        >
          <div key="a">widget a</div>
          <div key="b">widget b</div>
        </GridLayout>
      </StrictMode>
    );

    expect(screen.getByText("widget a")).toBeInTheDocument();
    expect(screen.getByText("widget b")).toBeInTheDocument();
    const joined = errors.map((a) => a.join(" ")).join("\n");
    expect(joined).not.toMatch(/findDOMNode|Warning:.*deprecated/i);
    spy.mockRestore();
  });
});
