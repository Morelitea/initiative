/**
 * The Report button.
 *
 * One rule holds on every surface it is drawn on, and it is the reason this is
 * a component rather than a line repeated five times: you cannot report your
 * own work, and a signed-out reader is offered nothing.
 */
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { buildUser } from "@/__tests__/factories";
import { renderWithProviders } from "@/__tests__/helpers/render";

vi.mock("@/hooks/useActiveGuildId", () => ({ useActiveGuildId: () => 3 }));
vi.mock("@/hooks/useReport", () => ({
  useFileReport: () => ({ mutate: vi.fn(), isPending: false }),
}));

import { ReportButton } from "./ReportButton";

const me = buildUser({ id: 10 });

const render = (props: Partial<React.ComponentProps<typeof ReportButton>> = {}) =>
  renderWithProviders(<ReportButton targetType="post" targetId={1} {...props} />, {
    auth: { user: me },
  });

describe("ReportButton", () => {
  it("is offered on somebody else's work", () => {
    render({ authorId: 99 });
    expect(screen.getByRole("button", { name: "Report" })).toBeInTheDocument();
  });

  it("is not offered on your own", () => {
    // Deleting or editing it is already there; a report about yourself is
    // somebody else's time.
    render({ authorId: me.id });
    expect(screen.queryByRole("button", { name: "Report" })).not.toBeInTheDocument();
  });

  it("is offered on something with no author", () => {
    render({ authorId: null });
    expect(screen.getByRole("button", { name: "Report" })).toBeInTheDocument();
  });

  it("is offered to nobody when nobody is signed in", () => {
    renderWithProviders(<ReportButton targetType="post" targetId={1} />, {
      auth: { user: null },
    });
    expect(screen.queryByRole("button", { name: "Report" })).not.toBeInTheDocument();
  });

  it("opens the dialog", async () => {
    render({ authorId: 99 });
    const user = userEvent.setup();

    await user.click(screen.getByRole("button", { name: "Report" }));
    expect(await screen.findByRole("dialog")).toBeInTheDocument();
    expect(screen.getByText("Report this")).toBeInTheDocument();
  });
});
