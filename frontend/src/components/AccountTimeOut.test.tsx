import { screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { renderWithProviders } from "@/__tests__/helpers/render";

const timeOut = vi.hoisted(() => ({
  value: { contact_email: null as string | null, reason: null as string | null, since: null },
}));

vi.mock("@/api/generated/users/users", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/api/generated/users/users")>()),
  readMyTimeOutApiV1UsersMeTimeOutGet: () => Promise.resolve(timeOut.value),
}));

import { AccountTimeOut } from "./AccountTimeOut";

describe("AccountTimeOut", () => {
  beforeEach(() => {
    timeOut.value = { contact_email: null, reason: null, since: null };
  });

  it("gives the reason and names who to contact", async () => {
    timeOut.value = { contact_email: "trust@example.com", reason: "Spam", since: null };
    renderWithProviders(<AccountTimeOut />);

    expect(screen.getByText("Your account is suspended")).toBeInTheDocument();
    expect(await screen.findByText("Reason given: Spam")).toBeInTheDocument();
    expect(screen.getByText("Contact trust@example.com about it.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Sign out" })).toBeInTheDocument();
  });

  it("says to contact whoever runs the server when nobody is named", async () => {
    renderWithProviders(<AccountTimeOut />);

    expect(
      await screen.findByText("Contact whoever runs this server about it.")
    ).toBeInTheDocument();
    expect(screen.queryByText(/Reason given/)).not.toBeInTheDocument();
  });
});
