/**
 * The mention popover is held open for a moment after the field loses focus,
 * so a click on it lands. That timer must not outlive the component: left to
 * run, it sets state on something that is gone — and when the test environment
 * has been torn down by then, on a `window` that no longer exists.
 */
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { renderWithProviders } from "@/__tests__/helpers/render";

import { CommentInput } from "./CommentInput";

vi.mock("./MentionPopover", () => ({ MentionPopover: () => null }));

/** The field is controlled, so a test drives it through its owner's state. */
const Host = ({ initial = "" }: { initial?: string }) => {
  const [value, setValue] = useState(initial);
  return <CommentInput initiativeId={1} value={value} onChange={setValue} onSubmit={vi.fn()} />;
};

const field = () => screen.getByRole("textbox") as HTMLTextAreaElement;

afterEach(() => vi.restoreAllMocks());

describe("the comment field", () => {
  it("cancels its blur timer when it goes away", async () => {
    const cleared = vi.spyOn(window, "clearTimeout");
    const { getByRole, unmount } = render(
      <CommentInput initiativeId={1} value="" onChange={vi.fn()} onSubmit={vi.fn()} />
    );

    const field = getByRole("textbox");
    await userEvent.click(field);
    await userEvent.tab();

    const pending = cleared.mock.calls.length;
    unmount();

    expect(cleared.mock.calls.length).toBeGreaterThan(pending);
  });

  it("shows the draft as it will read once posted", async () => {
    const user = userEvent.setup();
    renderWithProviders(
      <CommentInput
        initiativeId={1}
        value="Ship **now**, not later."
        onChange={vi.fn()}
        onSubmit={vi.fn()}
      />
    );

    await user.click(screen.getByRole("tab", { name: "Preview" }));

    expect(screen.getByText("now").tagName).toBe("STRONG");
  });

  it("writes a mention trigger from the toolbar, at a word boundary", async () => {
    const user = userEvent.setup();
    renderWithProviders(<Host initial="ask" />);

    field().setSelectionRange(3, 3);
    await user.click(screen.getByRole("button", { name: "Mention a member" }));

    expect(field()).toHaveValue("ask @");
  });

  it("leaves the caret on the trigger it just wrote, so the picker opens on it", async () => {
    const user = userEvent.setup();
    renderWithProviders(<Host />);

    await user.click(screen.getByRole("button", { name: "Link anything in this initiative" }));

    expect(field()).toHaveValue("#");
    await waitFor(() => expect(field().selectionStart).toBe(1));
  });
});
