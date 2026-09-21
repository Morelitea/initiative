/**
 * Asking someone their age, and what the surface promises about the answer.
 *
 * The load-bearing part is the promise: the date goes to the server to be
 * compared and is not kept — so the dialog has to say so, and must not hold on
 * to it either.
 *
 * This is the only place the question is put. Nothing here blocks the app: the
 * dialog sits in front of one button, and closing it leaves the account with
 * everything it already had.
 */
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { buildUser } from "@/__tests__/factories";
import { renderWithProviders } from "@/__tests__/helpers/render";

const post = vi.fn();

vi.mock("@/api/client", () => ({
  apiClient: { post: (...args: unknown[]) => post(...args) },
}));

import { AgeConfirmationDialog } from "@/components/guilds/AgeConfirmationDialog";

describe("AgeConfirmationDialog", () => {
  beforeEach(() => {
    post.mockReset().mockResolvedValue({ data: {} });
  });

  const renderDialog = (user?: ReturnType<typeof buildUser>) =>
    renderWithProviders(
      <AgeConfirmationDialog open onOpenChange={() => {}} onConfirmed={() => {}} />,
      user ? { auth: { user } } : undefined
    );

  /** Reach the date through the app's picker: open it, type the date, commit. */
  const enterBirthdate = async (date: string) => {
    await userEvent.click(await screen.findByLabelText("Date of birth"));
    const entry = await screen.findByLabelText("Type or pick a date");
    await userEvent.type(entry, `${date}{Enter}`);
    await userEvent.keyboard("{Escape}");
  };

  it("asks for a date of birth rather than offering a box to tick", async () => {
    renderDialog();

    await userEvent.click(await screen.findByLabelText("Date of birth"));

    // The app's own picker, not the browser's: a birthday is decades back, and
    // the year dropdown is how you get there.
    expect(await screen.findByLabelText("Type or pick a date")).toBeInTheDocument();
    expect(screen.queryByRole("checkbox")).not.toBeInTheDocument();
  });

  it("offers a lifetime of years to reach, and none the server would refuse", async () => {
    // Everything the calendar offers has to be a date the server accepts: born
    // by today, and no longer ago than the oldest person alive.
    renderDialog();

    await userEvent.click(await screen.findByLabelText("Date of birth"));
    const years = await screen.findByRole("combobox", { name: /year/i });
    const offered = within(years)
      .getAllByRole("option")
      .map((option) => option.textContent);

    // The server compares against the UTC date, so the window is that one.
    const thisYear = new Date().getUTCFullYear();
    expect(offered.at(-1)).toBe(String(thisYear));
    expect(offered[0]).toBe(String(thisYear - 120));
  });

  it("says what happens to the date, beside the field asking for it", async () => {
    renderDialog();

    expect(
      await screen.findByText(/records that you answered, never the date/i)
    ).toBeInTheDocument();
    expect(screen.getByText(/not sold, shared, or kept/i)).toBeInTheDocument();
  });

  it("says the question is only asked by the communities anyone can find", async () => {
    // The scope is the whole point of asking here rather than at the door: an
    // invited community is not this question's business.
    renderDialog();

    expect(
      await screen.findByText(/communities you were invited to never do/i)
    ).toBeInTheDocument();
  });

  it("sends the date and nothing else", async () => {
    renderDialog();

    await enterBirthdate("1990-05-04");
    await userEvent.click(screen.getByRole("button", { name: "Confirm and join" }));

    await waitFor(() => expect(post).toHaveBeenCalledTimes(1));
    expect(post).toHaveBeenCalledWith("/users/me/age-confirmation", {
      birthdate: "1990-05-04",
    });
  });

  it("cannot be submitted with no date", async () => {
    renderDialog();
    await screen.findByLabelText("Date of birth");

    expect(screen.getByRole("button", { name: "Confirm and join" })).toBeDisabled();
    expect(post).not.toHaveBeenCalled();
  });

  it("offers no second attempt to an account whose answer stands", async () => {
    // Re-asking would let the answer be tried until it came out right, which
    // is the thing recording it exists to stop.
    renderDialog(
      buildUser({ age_confirmed_at: null, age_below_minimum_at: "2026-01-01T00:00:00Z" })
    );

    expect(await screen.findByText(/told us you're not old enough yet/i)).toBeInTheDocument();
    expect(screen.queryByLabelText("Date of birth")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Confirm and join" })).not.toBeInTheDocument();
  });

  it("tells a blocked account the date was not kept and who can reset it", async () => {
    renderDialog(
      buildUser({ age_confirmed_at: null, age_below_minimum_at: "2026-01-01T00:00:00Z" })
    );

    expect(await screen.findByText(/did not keep the date you gave/i)).toBeInTheDocument();
  });

  it("tells a blocked account the communities it was invited to are unaffected", async () => {
    // The refusal closes one door. Saying so is what stops it reading as an
    // account that has been shut out of the app.
    renderDialog(
      buildUser({ age_confirmed_at: null, age_below_minimum_at: "2026-01-01T00:00:00Z" })
    );

    expect(
      await screen.findByText(/communities you were invited to is unaffected/i)
    ).toBeInTheDocument();
  });

  it("surfaces the server's answer when somebody is too young", async () => {
    post.mockRejectedValue({
      isAxiosError: true,
      response: { status: 422, data: { detail: "USER_AGE_BELOW_MINIMUM" } },
    });
    renderDialog();

    await enterBirthdate("2020-01-01");
    await userEvent.click(screen.getByRole("button", { name: "Confirm and join" }));

    expect(
      await screen.findByText(/16 or older to join a community anyone can find/i)
    ).toBeInTheDocument();
  });
});
