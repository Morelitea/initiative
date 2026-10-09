/**
 * Holding something for the platform: what it says before anything is held,
 * and what it sends.
 */
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { buildUser } from "@/__tests__/factories";
import { renderWithProviders } from "@/__tests__/helpers/render";

const place = vi.fn();

vi.mock("@/hooks/useHolds", () => ({
  usePlaceHold: () => ({ mutate: place, isPending: false }),
}));

import { HoldDialog, type HoldDialogProps } from "./HoldDialog";

const open = (props: Partial<HoldDialogProps> = {}) =>
  renderWithProviders(
    <HoldDialog
      open
      onOpenChange={() => {}}
      communityId={3}
      targetType="comment"
      targetId={42}
      {...props}
    />,
    { auth: { user: buildUser() } }
  );

describe("HoldDialog", () => {
  beforeEach(() => place.mockReset());

  it("holds it with a note for the platform", async () => {
    open();
    const user = userEvent.setup();
    await user.type(screen.getByLabelText(/Note for the platform/), "  Court order 12  ");
    await user.click(screen.getByRole("button", { name: "Hold it" }));
    expect(place).toHaveBeenCalledWith({
      target_type: "comment",
      target_id: 42,
      reason: "legal_request",
      legal_basis: null,
      note: "Court order 12",
      case_task_id: null,
    });
  });

  it("asks which law before holding something as illegal", async () => {
    open({ caseTaskId: 9 });
    const user = userEvent.setup();
    await user.click(screen.getByRole("combobox", { name: "Why" }));
    await user.click(await screen.findByRole("option", { name: "It may be illegal" }));
    expect(screen.getByRole("button", { name: "Hold it" })).toBeDisabled();
    await user.click(screen.getByRole("combobox", { name: "Which law" }));
    await user.click(await screen.findByRole("option", { name: "Privacy" }));
    await user.click(screen.getByRole("button", { name: "Hold it" }));
    expect(place).toHaveBeenCalledWith(
      expect.objectContaining({
        reason: "illegal_content",
        legal_basis: "privacy",
        case_task_id: 9,
      })
    );
  });
});
