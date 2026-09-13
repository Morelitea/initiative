/**
 * The address list.
 *
 * What is worth pinning here is the handful of rules the backend enforces and
 * this surface has to agree with, because disagreeing produces a button that
 * looks available and answers with an error: the primary and the last proven
 * address do not go, an unproven one is not offered as primary, and the ones
 * an IdP minted are not shown at all.
 */
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { renderWithProviders } from "@/__tests__/helpers/render";

import { AddressManager } from "./AddressManager";

const mocks = vi.hoisted(() => ({
  list: vi.fn(),
  add: vi.fn(),
  remove: vi.fn(),
  makePrimary: vi.fn(),
}));

vi.mock("@/hooks/useAddresses", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/hooks/useAddresses")>()),
  useMyAddresses: () => mocks.list(),
  useAddAddress: () => ({ mutate: mocks.add, isPending: false }),
  useRemoveAddress: () => ({ mutate: mocks.remove, isPending: false }),
  useMakeAddressPrimary: () => ({ mutate: mocks.makePrimary, isPending: false }),
}));

const address = (overrides: Record<string, unknown> = {}) => ({
  id: 1,
  email: "primary@example.com",
  verified: true,
  is_primary: true,
  source: "signup",
  created_at: "2026-01-01T00:00:00Z",
  last_login_at: null,
  ...overrides,
});

const listing = (...items: ReturnType<typeof address>[]) => ({
  data: { items },
  isLoading: false,
});

describe("AddressManager", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.list.mockReturnValue(listing(address()));
  });

  it("shows the addresses the account holds, primary first", () => {
    mocks.list.mockReturnValue(
      listing(
        address({ id: 2, email: "second@example.com", is_primary: false }),
        address({ id: 1, email: "primary@example.com", is_primary: true })
      )
    );

    renderWithProviders(<AddressManager />);

    const shown = screen.getAllByText(/@example\.com$/).map((node) => node.textContent);
    expect(shown).toEqual(["primary@example.com", "second@example.com"]);
  });

  it("does not show an address a provider minted", () => {
    mocks.list.mockReturnValue(
      listing(
        address(),
        address({
          id: 2,
          email: "abc123@oidc.local",
          verified: false,
          is_primary: false,
          source: "synthetic",
        })
      )
    );

    renderWithProviders(<AddressManager />);

    expect(screen.queryByText("abc123@oidc.local")).not.toBeInTheDocument();
  });

  it("does not remove the primary while it is the primary", () => {
    mocks.list.mockReturnValue(
      listing(
        address(),
        address({ id: 2, email: "second@example.com", verified: true, is_primary: false })
      )
    );

    renderWithProviders(<AddressManager />);

    // Another has to take its place first.
    expect(screen.getByLabelText(/primary@example\.com/)).toBeDisabled();
    // The second one is proven and is not the only one, so it goes.
    expect(screen.getByLabelText(/second@example\.com/)).toBeEnabled();
  });

  it("does not remove the only proven address, primary or not", () => {
    // An account that signed up before confirming and proved a second address
    // instead: the primary is unproven, and the one address that can sign them
    // in is not the primary. Removing it is the case the primary check misses.
    mocks.list.mockReturnValue(
      listing(
        address({ verified: false }),
        address({ id: 2, email: "proven@example.com", verified: true, is_primary: false })
      )
    );

    renderWithProviders(<AddressManager />);

    expect(screen.getByLabelText(/proven@example\.com/)).toBeDisabled();
  });

  it("offers primary only on an address that has been proven", () => {
    mocks.list.mockReturnValue(
      listing(
        address(),
        address({ id: 2, email: "unproven@example.com", verified: false, is_primary: false }),
        address({ id: 3, email: "proven@example.com", verified: true, is_primary: false })
      )
    );

    renderWithProviders(<AddressManager />);

    // One button, for the one address that could take the mail.
    expect(screen.getAllByRole("button", { name: /make primary/i })).toHaveLength(1);
  });

  it("says the same thing whether or not the address was free", async () => {
    const user = userEvent.setup();
    renderWithProviders(<AddressManager />);

    await user.type(screen.getByLabelText(/add an address/i), "new@example.com");
    await user.click(screen.getByRole("button", { name: /^add$/i }));

    expect(mocks.add).toHaveBeenCalledWith("new@example.com");
  });
});
