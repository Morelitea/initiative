/**
 * The second-factor step on the sign-in card.
 *
 * The password leg is answered elsewhere; what is worth pinning here is what
 * the card does with a challenge — that it stops asking for a password, that
 * the two kinds of code are sent as the kinds they are, that a refused code
 * leaves the person able to try again, and that starting over really does.
 */
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { renderPage } from "@/__tests__/helpers/render";

const mocks = vi.hoisted(() => ({
  login: vi.fn(),
  completeSecondFactor: vi.fn(),
  get: vi.fn(),
}));

vi.mock("@/api/client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/api/client")>()),
  apiClient: { get: (...args: unknown[]) => mocks.get(...args) },
}));

vi.mock("@/hooks/useAuth", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/hooks/useAuth")>()),
  useAuth: () => ({ login: mocks.login, completeSecondFactor: mocks.completeSecondFactor }),
}));

vi.mock("@/hooks/useServer", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/hooks/useServer")>()),
  useServer: () => ({
    isNativePlatform: false,
    isServerConfigured: true,
    getServerHostname: () => "example.com",
    getServerOrigin: () => "https://example.com",
    clearServerUrl: vi.fn(),
    serverUrl: "https://example.com",
  }),
}));

vi.mock("@/hooks/useAppConfig", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/hooks/useAppConfig")>()),
  useAppConfig: () => ({ passwordLoginEnabled: true }),
}));

import { SecondFactorRequiredError } from "@/hooks/useAuth";

import { LoginPage } from "./LoginPage";

const signIn = async (user: ReturnType<typeof userEvent.setup>) => {
  // The router resolves the route before anything renders.
  await user.type(await screen.findByLabelText(/email/i), "someone@example.com");
  await user.type(screen.getByLabelText(/password/i), "a-password");
  await user.click(screen.getByRole("button", { name: /sign in/i }));
};

const renderLogin = (search?: Record<string, string>) =>
  renderPage(LoginPage, { initialRoute: "/login", routerSearch: search });

const corp = {
  id: 1,
  slug: "corp",
  display_name: "Corp",
  kind: "oidc",
  login_url: "/api/v1/auth/corp/login",
  icon: null,
  button_style: null,
};

/** The page leaves for the provider by assigning the address, which jsdom will
 *  not follow. Stand a writable one in its place so the departure can be read
 *  back — the real `origin` and all, since that is what a path is judged
 *  against. */
const watchWhereItLeavesFor = () => {
  const original = window.location;
  const stand = { ...original, origin: original.origin, href: original.href };
  Object.defineProperty(window, "location", { value: stand, configurable: true, writable: true });
  return {
    left: () => stand.href,
    restore: () =>
      Object.defineProperty(window, "location", {
        value: original,
        configurable: true,
        writable: true,
      }),
  };
};

/** The bootstrap probe and the provider list share one client. */
const offering = (providers: unknown[]) => {
  mocks.get.mockImplementation((url: string) =>
    Promise.resolve(
      url === "/auth/providers" ? { data: { providers } } : { data: { has_users: true } }
    )
  );
};

describe("LoginPage second factor", () => {
  beforeEach(() => {
    mocks.login.mockReset();
    mocks.completeSecondFactor.mockReset().mockResolvedValue(undefined);
    // The bootstrap probe and the provider list both go through apiClient.get.
    // has_users false would send the page to first-run registration instead.
    mocks.get.mockReset().mockResolvedValue({ data: { has_users: true, providers: [] } });
  });

  it("asks for the code once the password is accepted", async () => {
    const user = userEvent.setup();
    mocks.login.mockRejectedValue(new SecondFactorRequiredError("a-challenge"));
    renderLogin();

    await signIn(user);

    await waitFor(() => expect(screen.getByLabelText(/authentication code/i)).toBeInTheDocument());
    // And it has stopped asking for the password it already has.
    expect(screen.queryByLabelText(/^password$/i)).not.toBeInTheDocument();
  });

  it("sends the code against the challenge it was given", async () => {
    const user = userEvent.setup();
    mocks.login.mockRejectedValue(new SecondFactorRequiredError("a-challenge"));
    renderLogin();
    await signIn(user);
    await screen.findByLabelText(/authentication code/i);

    await user.type(screen.getByLabelText(/authentication code/i), "123456");
    await user.click(screen.getByRole("button", { name: /continue/i }));

    await waitFor(() =>
      expect(mocks.completeSecondFactor).toHaveBeenCalledWith({
        challenge: "a-challenge",
        code: "123456",
      })
    );
  });

  it("sends a recovery code as a recovery code", async () => {
    const user = userEvent.setup();
    mocks.login.mockRejectedValue(new SecondFactorRequiredError("a-challenge"));
    renderLogin();
    await signIn(user);
    await screen.findByLabelText(/authentication code/i);

    await user.click(screen.getByRole("button", { name: /use a recovery code/i }));
    await user.type(screen.getByLabelText(/recovery code/i), "abcde-fghij");
    await user.click(screen.getByRole("button", { name: /continue/i }));

    await waitFor(() =>
      expect(mocks.completeSecondFactor).toHaveBeenCalledWith({
        challenge: "a-challenge",
        recoveryCode: "abcde-fghij",
      })
    );
  });

  it("lets them try again after a refused code", async () => {
    const user = userEvent.setup();
    mocks.login.mockRejectedValue(new SecondFactorRequiredError("a-challenge"));
    mocks.completeSecondFactor.mockRejectedValueOnce(new Error("That code isn't right."));
    renderLogin();
    await signIn(user);
    await screen.findByLabelText(/authentication code/i);

    await user.type(screen.getByLabelText(/authentication code/i), "000000");
    await user.click(screen.getByRole("button", { name: /continue/i }));

    expect(await screen.findByText("That code isn't right.")).toBeInTheDocument();
    // Still on the code step, with the field cleared to retype into.
    const field = screen.getByLabelText(/authentication code/i);
    expect(field).toBeInTheDocument();
    expect(field).toHaveValue("");
  });

  it("starting over puts the password back", async () => {
    const user = userEvent.setup();
    mocks.login.mockRejectedValue(new SecondFactorRequiredError("a-challenge"));
    renderLogin();
    await signIn(user);
    await screen.findByLabelText(/authentication code/i);

    await user.click(screen.getByRole("button", { name: /start over/i }));

    await waitFor(() => expect(screen.getByLabelText(/^password$/i)).toBeInTheDocument());
    expect(screen.queryByLabelText(/authentication code/i)).not.toBeInTheDocument();
  });
});

/**
 * Where signing in leaves you.
 *
 * Somebody who asked for a page and was sent here to sign in should land on
 * the page they asked for — the app sends a phone to a browser for a passkey
 * and that is the whole point of the trip. Only somewhere in this app,
 * though: anything else is dropped for the front page.
 */
describe("LoginPage return path", () => {
  beforeEach(() => {
    mocks.login.mockReset().mockResolvedValue(undefined);
    mocks.completeSecondFactor.mockReset();
    mocks.get.mockReset().mockResolvedValue({ data: { has_users: true, providers: [] } });
  });

  it("finishes the trip they were on", async () => {
    const user = userEvent.setup();
    const { router } = renderLogin({ next: "/profile/security" });

    await signIn(user);

    await waitFor(() => expect(router.state.location.pathname).toBe("/profile/security"));
  });

  it("keeps a destination outside this app out of it", async () => {
    const user = userEvent.setup();
    const { router } = renderLogin({ next: "//evil.test/take-me" });

    await signIn(user);

    await waitFor(() => expect(router.state.location.pathname).toBe("/"));
  });

  it("carries the same trip into a provider's sign-in", async () => {
    // An account that signs in through SSO only is the case the passkey trip
    // depends on: the app hands the browser the provider, and the provider's
    // callback is what lands somewhere.
    const user = userEvent.setup();
    offering([corp]);
    const departure = watchWhereItLeavesFor();
    try {
      renderLogin({ next: "/profile/security" });

      await user.click(await screen.findByRole("button", { name: /continue with corp/i }));

      expect(departure.left()).toBe("/api/v1/auth/corp/login?next=%2Fprofile%2Fsecurity");
    } finally {
      departure.restore();
    }
  });

  it("leaves for the provider bare when the trip was not one of ours", async () => {
    const user = userEvent.setup();
    offering([corp]);
    const departure = watchWhereItLeavesFor();
    try {
      renderLogin({ next: "//evil.test/take-me" });

      await user.click(await screen.findByRole("button", { name: /continue with corp/i }));

      expect(departure.left()).toBe("/api/v1/auth/corp/login");
    } finally {
      departure.restore();
    }
  });
});
