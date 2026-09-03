/**
 * Asking someone their age, and what the surface promises about the answer.
 *
 * The load-bearing part is the promise: the date goes to the server to be
 * compared and is not kept — so the screen has to say so, and must not hold on
 * to it either.
 */
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { buildUser } from "@/__tests__/factories";
import { renderWithProviders } from "@/__tests__/helpers/render";

const post = vi.fn();

vi.mock("@/api/client", () => ({
  apiClient: { post: (...args: unknown[]) => post(...args) },
}));

import { ConfirmAge } from "@/components/ConfirmAge";

describe("ConfirmAge", () => {
  beforeEach(() => {
    post.mockReset().mockResolvedValue({ data: {} });
  });

  it("asks for a date of birth rather than offering a box to tick", async () => {
    renderWithProviders(<ConfirmAge />);

    const field = await screen.findByLabelText("Date of birth");
    expect(field).toHaveAttribute("type", "date");
    expect(screen.queryByRole("checkbox")).not.toBeInTheDocument();
  });

  it("says what happens to the date, beside the field asking for it", async () => {
    renderWithProviders(<ConfirmAge />);

    expect(
      await screen.findByText(/records that you answered, never the date/i)
    ).toBeInTheDocument();
    expect(screen.getByText(/not sold, shared, or kept/i)).toBeInTheDocument();
  });

  it("says the question is only for the parts open to strangers", async () => {
    renderWithProviders(<ConfirmAge />);

    expect(await screen.findByText(/Private communities never do/i)).toBeInTheDocument();
  });

  it("sends the date and nothing else", async () => {
    renderWithProviders(<ConfirmAge />);

    await userEvent.type(await screen.findByLabelText("Date of birth"), "1990-05-04");
    await userEvent.click(screen.getByRole("button", { name: "Continue" }));

    await waitFor(() => expect(post).toHaveBeenCalledTimes(1));
    expect(post).toHaveBeenCalledWith("/users/me/age-confirmation", {
      birthdate: "1990-05-04",
    });
  });

  it("cannot be submitted with no date", async () => {
    renderWithProviders(<ConfirmAge />);
    await screen.findByLabelText("Date of birth");

    expect(screen.getByRole("button", { name: "Continue" })).toBeDisabled();
    expect(post).not.toHaveBeenCalled();
  });

  it("offers no second attempt to an account whose answer stands", async () => {
    // Re-asking would let the answer be tried until it came out right, which
    // is the thing recording it exists to stop.
    renderWithProviders(<ConfirmAge />, {
      auth: { user: buildUser({ age_below_minimum_at: "2026-01-01T00:00:00Z" }) },
    });

    expect(await screen.findByText(/told us you're not old enough yet/i)).toBeInTheDocument();
    expect(screen.queryByLabelText("Date of birth")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Continue" })).not.toBeInTheDocument();
  });

  it("tells a blocked account the date was not kept and who can reset it", async () => {
    renderWithProviders(<ConfirmAge />, {
      auth: { user: buildUser({ age_below_minimum_at: "2026-01-01T00:00:00Z" }) },
    });

    expect(await screen.findByText(/did not keep the date you gave/i)).toBeInTheDocument();
  });

  it("surfaces the server's answer when somebody is too young", async () => {
    post.mockRejectedValue({
      isAxiosError: true,
      response: { status: 422, data: { detail: "USER_AGE_BELOW_MINIMUM" } },
    });
    renderWithProviders(<ConfirmAge />);

    await userEvent.type(await screen.findByLabelText("Date of birth"), "2020-01-01");
    await userEvent.click(screen.getByRole("button", { name: "Continue" }));

    expect(
      await screen.findByText(/13 or older to take part in a community anyone can find/i)
    ).toBeInTheDocument();
  });
});
