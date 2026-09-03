/**
 * The mention popover is held open for a moment after the field loses focus,
 * so a click on it lands. That timer must not outlive the component: left to
 * run, it sets state on something that is gone — and when the test environment
 * has been torn down by then, on a `window` that no longer exists.
 */
import { render } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { CommentInput } from "./CommentInput";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

vi.mock("./MentionPopover", () => ({ MentionPopover: () => null }));

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
});
