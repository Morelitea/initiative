/**
 * Adding, renaming and removing a passkey.
 *
 * The add flow is the part worth pinning down: it is three steps that have to
 * stay joined — the server's options reach the browser, the browser's answer
 * reaches the server, and the name typed at the start travels with it. A
 * prompt that produced nothing has to leave the form as it was, so a second
 * attempt is one click rather than a retype.
 */
import { Browser } from "@capacitor/browser";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { renderWithProviders } from "@/__tests__/helpers/render";
import { toast } from "@/lib/chesterToast";

const mocks = vi.hoisted(() => ({
  list: vi.fn(),
  begin: vi.fn(),
  finish: vi.fn(),
  rename: vi.fn(),
  remove: vi.fn(),
  startRegistration: vi.fn(),
  browserSupportsWebAuthn: vi.fn(() => true),
}));

vi.mock("@/lib/chesterToast", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

vi.mock("@simplewebauthn/browser", () => ({
  startRegistration: (options: unknown) => mocks.startRegistration(options),
  browserSupportsWebAuthn: () => mocks.browserSupportsWebAuthn(),
  WebAuthnError: class WebAuthnError extends Error {},
}));

vi.mock("@/api/generated/auth/auth", () => ({
  getListPasskeysApiV1AuthPasskeysGetQueryKey: () => ["/api/v1/auth/passkeys"],
  useListPasskeysApiV1AuthPasskeysGet: () => mocks.list(),
  useBeginPasskeyRegistrationApiV1AuthPasskeysRegisterBeginPost: (options?: {
    mutation?: { onSuccess?: (data: unknown) => void | Promise<void> };
  }) => ({
    mutate: (vars: unknown) => {
      mocks.begin(vars);
      void options?.mutation?.onSuccess?.({ options: { challenge: "a-challenge" } });
    },
    isPending: false,
  }),
  useFinishPasskeyRegistrationApiV1AuthPasskeysRegisterFinishPost: (options?: {
    mutation?: { onSuccess?: (data: unknown) => void };
  }) => ({
    mutate: (vars: unknown) => {
      mocks.finish(vars);
      options?.mutation?.onSuccess?.({ id: "pk-new" });
    },
    isPending: false,
  }),
  useRenamePasskeyApiV1AuthPasskeysPasskeyIdPatch: (options?: {
    mutation?: { onSuccess?: (data: unknown) => void };
  }) => ({
    mutate: (vars: unknown) => {
      mocks.rename(vars);
      options?.mutation?.onSuccess?.({ id: "pk-1" });
    },
    isPending: false,
  }),
  useRemovePasskeyApiV1AuthPasskeysPasskeyIdRemovePost: (options?: {
    mutation?: { onSuccess?: () => void };
  }) => ({
    mutate: (vars: unknown) => {
      mocks.remove(vars);
      options?.mutation?.onSuccess?.();
    },
    isPending: false,
  }),
}));

import { PasskeysSection } from "./PasskeysSection";

const passkey = (overrides: Record<string, unknown> = {}) => ({
  id: "pk-1",
  name: "Work laptop",
  created_at: "2026-09-01T10:00:00Z",
  last_used_at: null,
  backed_up: false,
  user_verified: true,
  transports: ["internal"],
  aaguid: null,
  ...overrides,
});

const held = (passkeys: ReturnType<typeof passkey>[], rest: Record<string, unknown> = {}) => ({
  data: { passkeys, password_required: true, limit: 10, ...rest },
  isLoading: false,
  isError: false,
});

describe("PasskeysSection", () => {
  beforeEach(() => {
    for (const mock of Object.values(mocks)) mock.mockReset();
    mocks.browserSupportsWebAuthn.mockReturnValue(true);
    mocks.startRegistration.mockResolvedValue({ id: "credential-id", type: "public-key" });
    mocks.list.mockReturnValue(held([passkey()]));
  });

  it("names what the account holds, and marks the ones that travel", () => {
    mocks.list.mockReturnValue(
      held([passkey(), passkey({ id: "pk-2", name: "Phone", backed_up: true })])
    );
    renderWithProviders(<PasskeysSection />);

    expect(screen.getByText("Work laptop")).toBeInTheDocument();
    expect(screen.getByText("Phone")).toBeInTheDocument();
    expect(screen.getByText(/synced/i)).toBeInTheDocument();
  });

  it("says what a passkey is when there are none", () => {
    mocks.list.mockReturnValue(held([]));
    renderWithProviders(<PasskeysSection />);

    expect(screen.getByText(/no passkeys yet/i)).toBeInTheDocument();
    expect(screen.getByText(/password manager/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /add a passkey/i })).toBeEnabled();
  });

  it("carries the server's options to the browser and the browser's answer back", async () => {
    const user = userEvent.setup();
    renderWithProviders(<PasskeysSection />);

    await user.click(screen.getByRole("button", { name: /add a passkey/i }));
    await user.type(await screen.findByLabelText(/^name$/i), "Phone");
    await user.type(screen.getByLabelText(/current password/i), "a-password");
    await user.click(screen.getByRole("button", { name: /continue/i }));

    expect(mocks.begin).toHaveBeenCalledWith({ data: { current_password: "a-password" } });
    await waitFor(() =>
      expect(mocks.startRegistration).toHaveBeenCalledWith({
        optionsJSON: { challenge: "a-challenge" },
      })
    );
    await waitFor(() =>
      expect(mocks.finish).toHaveBeenCalledWith({
        data: { credential: { id: "credential-id", type: "public-key" }, name: "Phone" },
      })
    );
    expect(toast.success).toHaveBeenCalled();
  });

  it("keeps the form and the typed name when the prompt produces nothing", async () => {
    const user = userEvent.setup();
    const cancelled = new Error("The operation either timed out or was not allowed.");
    cancelled.name = "NotAllowedError";
    mocks.startRegistration.mockRejectedValue(cancelled);
    renderWithProviders(<PasskeysSection />);

    await user.click(screen.getByRole("button", { name: /add a passkey/i }));
    await user.type(await screen.findByLabelText(/^name$/i), "Phone");
    await user.type(screen.getByLabelText(/current password/i), "a-password");
    await user.click(screen.getByRole("button", { name: /continue/i }));

    expect(await screen.findByText(/you cancelled/i)).toBeInTheDocument();
    expect(mocks.finish).not.toHaveBeenCalled();
    expect(screen.getByLabelText(/^name$/i)).toHaveValue("Phone");
  });

  it("says so when this device already holds one for the site", async () => {
    const user = userEvent.setup();
    const already = new Error("The authenticator was previously registered.");
    already.name = "InvalidStateError";
    mocks.startRegistration.mockRejectedValue(already);
    renderWithProviders(<PasskeysSection />);

    await user.click(screen.getByRole("button", { name: /add a passkey/i }));
    await user.type(await screen.findByLabelText(/^name$/i), "Phone");
    await user.type(screen.getByLabelText(/current password/i), "a-password");
    await user.click(screen.getByRole("button", { name: /continue/i }));

    expect(await screen.findByText(/already holds a passkey/i)).toBeInTheDocument();
  });

  it("says so when the address is not the one the site is set up under", async () => {
    const user = userEvent.setup();
    const mismatch = new Error("The relying party ID is not a registrable domain suffix.");
    mismatch.name = "SecurityError";
    mocks.startRegistration.mockRejectedValue(mismatch);
    renderWithProviders(<PasskeysSection />);

    await user.click(screen.getByRole("button", { name: /add a passkey/i }));
    await user.type(await screen.findByLabelText(/^name$/i), "Phone");
    await user.type(screen.getByLabelText(/current password/i), "a-password");
    await user.click(screen.getByRole("button", { name: /continue/i }));

    expect(await screen.findByText(/doesn't match the address/i)).toBeInTheDocument();
  });

  it("asks for the password before taking a way in away", async () => {
    const user = userEvent.setup();
    renderWithProviders(<PasskeysSection />);

    await user.click(screen.getByRole("button", { name: /remove/i }));
    await user.type(await screen.findByLabelText(/current password/i), "a-password");
    await user.click(screen.getAllByRole("button", { name: /remove/i }).at(-1) as HTMLElement);

    await waitFor(() =>
      expect(mocks.remove).toHaveBeenCalledWith({
        passkeyId: "pk-1",
        data: { current_password: "a-password" },
      })
    );
  });

  it("sends a new name on its own", async () => {
    const user = userEvent.setup();
    renderWithProviders(<PasskeysSection />);

    await user.click(screen.getByRole("button", { name: /rename/i }));
    const field = await screen.findByLabelText(/^name$/i);
    await user.clear(field);
    await user.type(field, "Old laptop");
    await user.click(screen.getByRole("button", { name: /^save$/i }));

    await waitFor(() =>
      expect(mocks.rename).toHaveBeenCalledWith({
        passkeyId: "pk-1",
        data: { name: "Old laptop" },
      })
    );
  });

  it("stops offering to add one at the limit", () => {
    mocks.list.mockReturnValue(
      held([passkey(), passkey({ id: "pk-2", name: "Phone" })], { limit: 2 })
    );
    renderWithProviders(<PasskeysSection />);

    expect(screen.getByRole("button", { name: /add a passkey/i })).toBeDisabled();
    expect(screen.getByText(/remove one to add another/i)).toBeInTheDocument();
  });

  it("stops offering to add one where the browser cannot make it", () => {
    mocks.browserSupportsWebAuthn.mockReturnValue(false);
    renderWithProviders(<PasskeysSection />);

    expect(screen.getByRole("button", { name: /add a passkey/i })).toBeDisabled();
    expect(screen.getByText(/can't make a passkey/i)).toBeInTheDocument();
  });

  it("sends a phone to the system browser instead of running the ceremony", async () => {
    // A passkey belongs to the deployment's domain, and the browser is what
    // decides which domain it is in.
    const user = userEvent.setup();
    renderWithProviders(<PasskeysSection />, {
      server: {
        isNativePlatform: true,
        serverUrl: "https://example.test/api/v1",
        getServerOrigin: vi.fn().mockReturnValue("https://example.test"),
      },
    });

    await user.click(screen.getByRole("button", { name: /add a passkey/i }));

    expect(Browser.open).toHaveBeenCalledWith({ url: "https://example.test/profile/security" });
    expect(mocks.begin).not.toHaveBeenCalled();
    expect(screen.queryByLabelText(/current password/i)).not.toBeInTheDocument();
  });
});
