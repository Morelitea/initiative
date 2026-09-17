/**
 * Turning two-factor on, off, and round again.
 *
 * The section's own job is small but easy to get subtly wrong: the password
 * step serves two errands and they must not be confused, and "turn off" takes
 * either kind of code and has to send each as the kind it is.
 */
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { renderWithProviders } from "@/__tests__/helpers/render";

const mocks = vi.hoisted(() => ({
  status: vi.fn(),
  begin: vi.fn(),
  confirm: vi.fn(),
  disable: vi.fn(),
  regenerate: vi.fn(),
}));

vi.mock("@/api/generated/auth/auth", () => ({
  useReadSecondFactorApiV1AuthTotpGet: () => mocks.status(),
  useBeginSecondFactorApiV1AuthTotpEnrollPost: (options?: {
    mutation?: { onSuccess?: (data: unknown) => void };
  }) => ({
    mutate: (vars: unknown) => {
      mocks.begin(vars);
      options?.mutation?.onSuccess?.({
        secret: "SEEDSEEDSEED",
        otpauth_uri: "otpauth://totp/example.com:me?secret=SEEDSEEDSEED",
      });
    },
    isPending: false,
  }),
  useConfirmSecondFactorApiV1AuthTotpConfirmPost: (options?: {
    mutation?: { onSuccess?: (data: unknown) => void };
  }) => ({
    mutate: (vars: unknown) => {
      mocks.confirm(vars);
      options?.mutation?.onSuccess?.({ codes: ["aaaaa-bbbbb", "ccccc-ddddd"] });
    },
    isPending: false,
  }),
  useDisableSecondFactorApiV1AuthTotpDisablePost: (options?: {
    mutation?: { onSuccess?: () => void };
  }) => ({
    mutate: (vars: unknown) => {
      mocks.disable(vars);
      options?.mutation?.onSuccess?.();
    },
    isPending: false,
  }),
  useRegenerateRecoveryCodesApiV1AuthRecoveryCodesRegeneratePost: (options?: {
    mutation?: { onSuccess?: (data: unknown) => void };
  }) => ({
    mutate: (vars: unknown) => {
      mocks.regenerate(vars);
      options?.mutation?.onSuccess?.({ codes: ["eeeee-fffff"] });
    },
    isPending: false,
  }),
}));

vi.mock("@/hooks/useAuth", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/hooks/useAuth")>()),
  useAuth: () => ({ user: { has_federated_identity: false } }),
}));

import { TwoFactorSection } from "./TwoFactorSection";

const notEnrolled = { data: { enrolled: false, recovery_codes_remaining: 0 }, isLoading: false };
const enrolled = {
  data: {
    enrolled: true,
    confirmed_at: "2026-09-01T10:00:00Z",
    last_used_at: null,
    recovery_codes_remaining: 8,
  },
  isLoading: false,
};

describe("TwoFactorSection", () => {
  beforeEach(() => {
    for (const mock of Object.values(mocks)) mock.mockReset();
    mocks.status.mockReturnValue(notEnrolled);
  });

  it("offers to set it up when the account has none", () => {
    renderWithProviders(<TwoFactorSection />);
    expect(screen.getByRole("button", { name: /set up/i })).toBeInTheDocument();
  });

  it("walks password, then scan, then the codes", async () => {
    const user = userEvent.setup();
    renderWithProviders(<TwoFactorSection />);

    await user.click(screen.getByRole("button", { name: /set up/i }));
    await user.type(await screen.findByLabelText(/current password/i), "a-password");
    await user.click(screen.getByRole("button", { name: /continue/i }));

    expect(mocks.begin).toHaveBeenCalledWith({ data: { current_password: "a-password" } });
    // The seed is offered as text as well as a QR, for a device that cannot scan.
    expect(await screen.findByText("SEEDSEEDSEED")).toBeInTheDocument();

    await user.type(screen.getByLabelText(/code from your app/i), "123456");
    await user.click(screen.getByRole("button", { name: /turn on/i }));

    expect(mocks.confirm).toHaveBeenCalledWith({ data: { code: "123456" } });
    expect(await screen.findByText("aaaaa-bbbbb")).toBeInTheDocument();
  });

  it("shows what the account holds once it is on", () => {
    mocks.status.mockReturnValue(enrolled);
    renderWithProviders(<TwoFactorSection />);

    expect(screen.getByText(/8 recovery codes left/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /turn off/i })).toBeInTheDocument();
  });

  it("asks the regenerate endpoint, not the enrol one", async () => {
    // The password step serves both errands; before it was told which, this
    // button started a fresh enrolment.
    const user = userEvent.setup();
    mocks.status.mockReturnValue(enrolled);
    renderWithProviders(<TwoFactorSection />);

    await user.click(screen.getByRole("button", { name: /new recovery codes/i }));
    await user.type(await screen.findByLabelText(/current password/i), "a-password");
    await user.click(screen.getByRole("button", { name: /continue/i }));

    expect(mocks.regenerate).toHaveBeenCalledWith({ data: { current_password: "a-password" } });
    expect(mocks.begin).not.toHaveBeenCalled();
    expect(await screen.findByText("eeeee-fffff")).toBeInTheDocument();
  });

  it("sends six digits as a live code", async () => {
    const user = userEvent.setup();
    mocks.status.mockReturnValue(enrolled);
    renderWithProviders(<TwoFactorSection />);

    await user.click(screen.getByRole("button", { name: /turn off/i }));
    await user.type(await screen.findByLabelText(/current password/i), "a-password");
    await user.type(screen.getByLabelText(/recovery code/i), "123456");
    await user.click(screen.getAllByRole("button", { name: /turn off/i }).at(-1) as HTMLElement);

    await waitFor(() =>
      expect(mocks.disable).toHaveBeenCalledWith({
        data: { current_password: "a-password", code: "123456" },
      })
    );
  });

  it("sends anything else as a recovery code", async () => {
    const user = userEvent.setup();
    mocks.status.mockReturnValue(enrolled);
    renderWithProviders(<TwoFactorSection />);

    await user.click(screen.getByRole("button", { name: /turn off/i }));
    await user.type(await screen.findByLabelText(/current password/i), "a-password");
    await user.type(screen.getByLabelText(/recovery code/i), "aaaaa-bbbbb");
    await user.click(screen.getAllByRole("button", { name: /turn off/i }).at(-1) as HTMLElement);

    await waitFor(() =>
      expect(mocks.disable).toHaveBeenCalledWith({
        data: { current_password: "a-password", recovery_code: "aaaaa-bbbbb" },
      })
    );
  });
});
