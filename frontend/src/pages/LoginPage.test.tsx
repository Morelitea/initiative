/**
 * The sign-in card's two steps beyond a password: the second factor, and the
 * passkey.
 *
 * For the factor, what is worth pinning is what the card does with a challenge
 * — that it stops asking for a password, that the two kinds of code are sent
 * as the kinds they are, that a refused code leaves the person able to try
 * again, and that starting over really does.
 *
 * For the passkey it is the joins: that the button is there only where both
 * the deployment and the browser offer one, that a press stands down whatever
 * prompt was already waiting, and that the two ways the ceremony can end —
 * a session for this browser, a way back to an app — each go where they go.
 */
import { Browser } from "@capacitor/browser";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { renderPage } from "@/__tests__/helpers/render";

const mocks = vi.hoisted(() => ({
  login: vi.fn(),
  completeSecondFactor: vi.fn(),
  applyPasskeySignIn: vi.fn(),
  get: vi.fn(),
  signInWithPasskey: vi.fn(),
  cancelPendingPasskeyPrompt: vi.fn(),
  browserOffersPasskeys: vi.fn(() => true),
  browserOffersPasskeyAutofill: vi.fn(() => Promise.resolve(false)),
  /** The real mapping, so the card is asserted on the copy it would show. */
  describePasskeyPromptError: vi.fn((error: unknown) => {
    const name = error instanceof Error ? error.name : "";
    if (name === "AbortError") return null;
    return name === "NotAllowedError" ? "auth:login.passkeyCancelled" : "auth:login.passkeyFailed";
  }),
  /** Read on every render, so a test can say what the deployment offers. */
  config: { passwordLoginEnabled: true, passkeyLoginEnabled: true },
  server: { isNativePlatform: false },
}));

vi.mock("@/api/client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/api/client")>()),
  apiClient: { get: (...args: unknown[]) => mocks.get(...args) },
}));

vi.mock("@/hooks/useAuth", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/hooks/useAuth")>()),
  useAuth: () => ({
    login: mocks.login,
    completeSecondFactor: mocks.completeSecondFactor,
    applyPasskeySignIn: mocks.applyPasskeySignIn,
  }),
}));

vi.mock("@/hooks/useServer", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/hooks/useServer")>()),
  useServer: () => ({
    isNativePlatform: mocks.server.isNativePlatform,
    isServerConfigured: true,
    getServerHostname: () => "example.com",
    getServerOrigin: () => "https://example.com",
    clearServerUrl: vi.fn(),
    serverUrl: "https://example.com",
  }),
}));

vi.mock("@/hooks/useAppConfig", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/hooks/useAppConfig")>()),
  useAppConfig: () => mocks.config,
}));

// Every conversation with the browser's credential API goes through this one
// module, so the whole ceremony is one mock.
vi.mock("@/lib/passkeys", () => ({
  browserOffersPasskeys: () => mocks.browserOffersPasskeys(),
  browserOffersPasskeyAutofill: () => mocks.browserOffersPasskeyAutofill(),
  signInWithPasskey: (options?: unknown) => mocks.signInWithPasskey(options),
  cancelPendingPasskeyPrompt: () => mocks.cancelPendingPasskeyPrompt(),
  describePasskeyPromptError: (error: unknown) => mocks.describePasskeyPromptError(error),
}));

import { SecondFactorRequiredError } from "@/hooks/useAuth";

import { LoginPage } from "./LoginPage";

const signIn = async (user: ReturnType<typeof userEvent.setup>) => {
  // The router resolves the route before anything renders.
  await user.type(await screen.findByLabelText(/email/i), "someone@example.com");
  await user.type(screen.getByLabelText(/password/i), "a-password");
  // Anchored: the passkey button beside it also starts with "Sign in with".
  await user.click(screen.getByRole("button", { name: /^sign in$/i }));
};

const renderLogin = (search?: Record<string, unknown>) =>
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

const passkeyButton = () => screen.findByRole("button", { name: /sign in with a passkey/i });

const resetLoginMocks = () => {
  mocks.login.mockReset();
  mocks.completeSecondFactor.mockReset().mockResolvedValue(undefined);
  mocks.applyPasskeySignIn.mockReset().mockResolvedValue(undefined);
  mocks.signInWithPasskey.mockReset();
  mocks.cancelPendingPasskeyPrompt.mockReset();
  mocks.browserOffersPasskeys.mockReset().mockReturnValue(true);
  mocks.browserOffersPasskeyAutofill.mockReset().mockResolvedValue(false);
  mocks.config = { passwordLoginEnabled: true, passkeyLoginEnabled: true };
  mocks.server = { isNativePlatform: false };
  vi.mocked(Browser.open).mockClear();
  // The bootstrap probe and the provider list both go through apiClient.get.
  // has_users false would send the page to first-run registration instead.
  mocks.get.mockReset().mockResolvedValue({ data: { has_users: true, providers: [] } });
};

describe("LoginPage second factor", () => {
  beforeEach(resetLoginMocks);

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
    resetLoginMocks();
    mocks.login.mockResolvedValue(undefined);
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

describe("LoginPage passkey", () => {
  beforeEach(resetLoginMocks);

  it("offers one where the deployment and the browser both do", async () => {
    renderLogin();

    expect(await passkeyButton()).toBeEnabled();
  });

  it("offers none where the deployment has withdrawn them", async () => {
    mocks.config = { passwordLoginEnabled: true, passkeyLoginEnabled: false };
    renderLogin();

    await screen.findByLabelText(/email/i);
    expect(screen.queryByRole("button", { name: /passkey/i })).not.toBeInTheDocument();
  });

  it("offers none where this browser cannot present one", async () => {
    mocks.browserOffersPasskeys.mockReturnValue(false);
    renderLogin();

    await screen.findByLabelText(/email/i);
    expect(screen.queryByRole("button", { name: /passkey/i })).not.toBeInTheDocument();
  });

  it("stands the waiting prompt down, signs in, and goes on", async () => {
    const user = userEvent.setup();
    const session = { access_token: "fresh-token", token_type: "bearer" };
    mocks.signInWithPasskey.mockResolvedValue(session);
    const { router } = renderLogin();

    await user.click(await passkeyButton());

    expect(mocks.cancelPendingPasskeyPrompt).toHaveBeenCalled();
    expect(mocks.signInWithPasskey).toHaveBeenCalledWith({ conditional: false });
    await waitFor(() => expect(mocks.applyPasskeySignIn).toHaveBeenCalledWith(session));
    await waitFor(() => expect(router.state.location.pathname).toBe("/"));
  });

  it("says so when the prompt produces nothing", async () => {
    const user = userEvent.setup();
    const cancelled = new Error("The operation either timed out or was not allowed.");
    cancelled.name = "NotAllowedError";
    mocks.signInWithPasskey.mockRejectedValue(cancelled);
    renderLogin();

    await user.click(await passkeyButton());

    expect(await screen.findByText(/you cancelled/i)).toBeInTheDocument();
    expect(mocks.applyPasskeySignIn).not.toHaveBeenCalled();
  });

  it("waits in the browser's autofill from the moment the page opens", async () => {
    const session = { access_token: "fresh-token", token_type: "bearer" };
    mocks.browserOffersPasskeyAutofill.mockResolvedValue(true);
    mocks.signInWithPasskey.mockResolvedValue(session);
    renderLogin();

    await waitFor(() =>
      expect(mocks.signInWithPasskey).toHaveBeenCalledWith({ conditional: true })
    );
    await waitFor(() => expect(mocks.applyPasskeySignIn).toHaveBeenCalledWith(session));
  });

  it("lets the browser offer a passkey beside the saved addresses", async () => {
    renderLogin();

    expect(await screen.findByLabelText(/email/i)).toHaveAttribute(
      "autocomplete",
      "username webauthn"
    );
  });

  it("sends a phone to a browser rather than prompting in the app", async () => {
    // A passkey belongs to the deployment's domain, and the browser is what
    // decides which domain it is in.
    const user = userEvent.setup();
    mocks.server = { isNativePlatform: true };
    renderLogin();

    await user.click(await passkeyButton());

    expect(Browser.open).toHaveBeenCalledWith({
      url: "https://example.com/login?passkey=1&mobile=true&device_name=Test%20Device",
    });
    expect(mocks.signInWithPasskey).not.toHaveBeenCalled();
  });
});

describe("LoginPage passkey relay", () => {
  const relaySearch = { passkey: 1, mobile: true, device_name: "Pixel" };
  const originalLocation = Object.getOwnPropertyDescriptor(window, "location");
  let assign: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    resetLoginMocks();
    assign = vi.fn();
    Object.defineProperty(window, "location", {
      configurable: true,
      value: { href: window.location.href, origin: window.location.origin, assign },
    });
  });

  afterEach(() => {
    if (originalLocation) Object.defineProperty(window, "location", originalLocation);
  });

  it("asks for one press and nothing else", async () => {
    renderLogin(relaySearch);

    expect(
      await screen.findByRole("button", { name: /continue with a passkey/i })
    ).toBeInTheDocument();
    // Not the sign-in card: this browser was opened for one thing.
    expect(screen.queryByLabelText(/email/i)).not.toBeInTheDocument();
    // And nothing starts on its own — the prompt wants a press behind it.
    expect(mocks.signInWithPasskey).not.toHaveBeenCalled();
  });

  it("hands the app the way back", async () => {
    const user = userEvent.setup();
    mocks.signInWithPasskey.mockResolvedValue({
      token_type: "bearer",
      redirect_to: "initiative://oidc/callback?token=abc&token_type=device_token",
    });
    renderLogin(relaySearch);

    await user.click(await screen.findByRole("button", { name: /continue with a passkey/i }));

    expect(mocks.signInWithPasskey).toHaveBeenCalledWith({ mobile: true, deviceName: "Pixel" });
    await waitFor(() =>
      expect(assign).toHaveBeenCalledWith(
        "initiative://oidc/callback?token=abc&token_type=device_token"
      )
    );
    expect(await screen.findByText(/go back to the app/i)).toBeInTheDocument();
  });

  it("keeps the button when the ceremony is refused", async () => {
    const user = userEvent.setup();
    const cancelled = new Error("The operation either timed out or was not allowed.");
    cancelled.name = "NotAllowedError";
    mocks.signInWithPasskey.mockRejectedValue(cancelled);
    renderLogin(relaySearch);

    await user.click(await screen.findByRole("button", { name: /continue with a passkey/i }));

    expect(await screen.findByText(/you cancelled/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /continue with a passkey/i })).toBeEnabled();
    expect(assign).not.toHaveBeenCalled();
  });
});
