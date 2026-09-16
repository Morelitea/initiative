/**
 * The Report dialog.
 *
 * The same dialog from every surface, and what it must not do is as important
 * as what it does: it never says where the report went, and it tells the
 * reporter nothing about what happens next.
 */
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { buildUser } from "@/__tests__/factories";
import { renderWithProviders } from "@/__tests__/helpers/render";

const fileMutate = vi.fn();

vi.mock("@/hooks/useReport", () => ({
  useFileReport: () => ({ mutate: fileMutate, isPending: false }),
}));

import { ReportDialog } from "./ReportDialog";

const render = (props: Partial<React.ComponentProps<typeof ReportDialog>> = {}) =>
  renderWithProviders(
    <ReportDialog
      open
      onOpenChange={() => {}}
      targetType="comment"
      targetId={42}
      guildId={3}
      {...props}
    />,
    { auth: { user: buildUser() } }
  );

const chooseReason = async (user: ReturnType<typeof userEvent.setup>, name: string) => {
  await user.click(screen.getByRole("combobox", { name: "What is wrong?" }));
  await user.click(await screen.findByRole("option", { name }));
};

describe("ReportDialog", () => {
  beforeEach(() => fileMutate.mockClear());

  it("will not send without a reason", () => {
    render();
    expect(screen.getByRole("button", { name: "Send report" })).toBeDisabled();
  });

  it("sends the target, the reason and the community it was reported from", async () => {
    render();
    const user = userEvent.setup();

    await chooseReason(user, "Harassment");
    await user.click(screen.getByRole("button", { name: "Send report" }));

    expect(fileMutate).toHaveBeenCalledWith({
      target_type: "comment",
      target_id: 42,
      reason: "harassment",
      detail: null,
      guild_id: 3,
    });
  });

  it("carries the reporter's own words", async () => {
    render();
    const user = userEvent.setup();

    await user.type(screen.getByLabelText("Anything else?"), "  This is abusive.  ");
    await chooseReason(user, "Hate");
    await user.click(screen.getByRole("button", { name: "Send report" }));

    expect(fileMutate).toHaveBeenCalledWith(
      expect.objectContaining({ detail: "This is abusive.", reason: "hate" })
    );
  });

  it("sends no community when the reporter is not in one", async () => {
    render({ targetType: "user_profile", targetId: 7, guildId: null });
    const user = userEvent.setup();

    await chooseReason(user, "Spam");
    await user.click(screen.getByRole("button", { name: "Send report" }));

    expect(fileMutate).toHaveBeenCalledWith(
      expect.objectContaining({ target_type: "user_profile", guild_id: null })
    );
  });

  it("never says where the report will go", () => {
    render();
    // Nothing in the dialog names a venue, a project or a moderator: where it
    // goes is decided server-side and is not the reporter's business.
    for (const leak of [/moderator/i, /platform/i, /operations/i, /initiative/i]) {
      expect(screen.queryByText(leak)).not.toBeInTheDocument();
    }
  });
});
