/**
 * Where "This wasn't me" in an account email lands.
 *
 * Opening the link must change nothing, because mail scanners open links:
 * the page reads the token and says what the email was about, and only the
 * button signs the account out everywhere.
 */
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse, http } from "msw";
import { describe, expect, it, vi } from "vitest";

import { buildUser } from "@/__tests__/factories";
import { server } from "@/__tests__/helpers/msw-server";
import { renderPage } from "@/__tests__/helpers/render";

import { AccountNotMePage } from "./AccountNotMePage";

const PAGE = {
  initialRoute: "/account/not-me",
  routerSearch: { token: "a-token-from-the-email" },
};

describe("AccountNotMePage", () => {
  it("signs out everywhere only when the button is pressed", async () => {
    const user = userEvent.setup();
    const refreshUser = vi.fn().mockResolvedValue(undefined);
    const signOuts: unknown[] = [];
    server.use(
      http.post("/api/v1/auth/account-change/read", () =>
        HttpResponse.json({ notice: "passkey.added", sign_out: true, undo: null, subject: null })
      ),
      http.post("/api/v1/auth/account-change/sign-out", async ({ request }) => {
        signOuts.push(await request.json());
        return HttpResponse.json({ status: "signed_out" });
      })
    );

    renderPage(AccountNotMePage, { ...PAGE, auth: { user: buildUser(), refreshUser } });

    expect(await screen.findByText(/a change to your passkeys/i)).toBeInTheDocument();
    expect(signOuts).toEqual([]);

    await user.click(screen.getByRole("button", { name: /sign out everywhere/i }));

    expect(await screen.findByText(/you're signed out everywhere/i)).toBeInTheDocument();
    expect(signOuts).toEqual([{ token: "a-token-from-the-email" }]);
    // A signed-in browser asks after its own session, which may be one of
    // those just ended.
    expect(refreshUser).toHaveBeenCalledTimes(1);
  });

  it("says so when the link has expired or been used", async () => {
    server.use(
      http.post("/api/v1/auth/account-change/read", () =>
        HttpResponse.json({ detail: "INVALID_OR_EXPIRED_TOKEN" }, { status: 400 })
      )
    );

    renderPage(AccountNotMePage, PAGE);

    expect(await screen.findByText(/this link doesn't work/i)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /sign out everywhere/i })).not.toBeInTheDocument();
  });

  it("undoes the change where this copy of the email may", async () => {
    const user = userEvent.setup();
    const undos: unknown[] = [];
    server.use(
      http.post("/api/v1/auth/account-change/read", () =>
        HttpResponse.json({
          notice: "address.removed",
          sign_out: false,
          undo: "removed",
          subject: "me@example.com",
        })
      ),
      http.post("/api/v1/auth/account-change/undo", async ({ request }) => {
        undos.push(await request.json());
        return HttpResponse.json({ status: "undone" });
      })
    );

    renderPage(AccountNotMePage, PAGE);

    expect(
      await screen.findByText(/me@example.com goes back on your account/i)
    ).toBeInTheDocument();
    // A copy to an address the account no longer holds only puts it back.
    expect(
      screen.queryByRole("button", { name: /only sign out everywhere/i })
    ).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /undo it and sign out everywhere/i }));

    expect(await screen.findByText(/^undone/i)).toBeInTheDocument();
    expect(undos).toEqual([{ token: "a-token-from-the-email" }]);
  });
});
