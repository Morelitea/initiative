import { act, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse, http } from "msw";
import { describe, expect, it, vi } from "vitest";

import { server } from "@/__tests__/helpers/msw-server";
import { renderPage, renderWithProviders } from "@/__tests__/helpers/render";
import { AUTH_FACTOR_REQUIRED_EVENT } from "@/api/client";

import { SecondFactorStepUpDialog } from "./SecondFactorStepUpDialog";

const statusIs = (enrolled: boolean) =>
  server.use(
    http.get("/api/v1/auth/totp", () =>
      HttpResponse.json({ enrolled, recovery_codes_remaining: enrolled ? 8 : 0 })
    )
  );

const passkeysAre = (passkeys: { id: string; name: string }[]) =>
  server.use(
    http.get("/api/v1/auth/passkeys", () =>
      HttpResponse.json({ passkeys, limit: 10, password_required: true, offered: true })
    )
  );

const fireChallenge = ({
  guildId = 4,
  kind = "totp",
}: {
  guildId?: number | null;
  kind?: "totp" | "passkey";
} = {}) => {
  act(() => {
    window.dispatchEvent(
      new CustomEvent(AUTH_FACTOR_REQUIRED_EVENT, { detail: { guildId, kind } })
    );
  });
};

describe("SecondFactorStepUpDialog", () => {
  it("stays shut until a community asks", () => {
    statusIs(true);
    renderWithProviders(<SecondFactorStepUpDialog />);

    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("adds the authenticator code to the session already open", async () => {
    statusIs(true);
    const stepUpWithFactor = vi.fn().mockResolvedValue(undefined);
    renderWithProviders(<SecondFactorStepUpDialog />, { auth: { stepUpWithFactor } });

    fireChallenge();
    await screen.findByRole("dialog");

    await userEvent.type(screen.getByLabelText(/authentication code/i), "123456");
    await userEvent.click(screen.getByRole("button", { name: /continue/i }));

    await waitFor(() => {
      expect(stepUpWithFactor).toHaveBeenCalledWith({ code: "123456" });
    });
    // The page behind it carries on rather than needing a reload.
    await waitFor(() => {
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    });
  });

  it("reads a code the way an authenticator shows it", async () => {
    statusIs(true);
    const stepUpWithFactor = vi.fn().mockResolvedValue(undefined);
    renderWithProviders(<SecondFactorStepUpDialog />, { auth: { stepUpWithFactor } });

    fireChallenge();
    await screen.findByRole("dialog");

    // An authenticator app displays "123 456", and that is what gets pasted.
    await userEvent.type(screen.getByLabelText(/authentication code/i), "123 456");
    await userEvent.click(screen.getByRole("button", { name: /continue/i }));

    await waitFor(() => {
      expect(stepUpWithFactor).toHaveBeenCalledWith({ code: "123456" });
    });
  });

  it("takes a recovery code instead", async () => {
    statusIs(true);
    const stepUpWithFactor = vi.fn().mockResolvedValue(undefined);
    renderWithProviders(<SecondFactorStepUpDialog />, { auth: { stepUpWithFactor } });

    fireChallenge();
    await screen.findByRole("dialog");
    await userEvent.click(screen.getByRole("button", { name: /use a recovery code/i }));

    await userEvent.type(screen.getByLabelText(/recovery code/i), "abcde-fghij");
    await userEvent.click(screen.getByRole("button", { name: /continue/i }));

    await waitFor(() => {
      expect(stepUpWithFactor).toHaveBeenCalledWith({ recoveryCode: "abcde-fghij" });
    });
  });

  it("keeps the dialog open and says so when the code is refused", async () => {
    statusIs(true);
    const stepUpWithFactor = vi.fn().mockRejectedValue(new Error("nope"));
    renderWithProviders(<SecondFactorStepUpDialog />, { auth: { stepUpWithFactor } });

    fireChallenge();
    await screen.findByRole("dialog");

    await userEvent.type(screen.getByLabelText(/authentication code/i), "000000");
    await userEvent.click(screen.getByRole("button", { name: /continue/i }));

    await waitFor(() => {
      expect(screen.getByRole("dialog")).toBeInTheDocument();
    });
    expect(screen.getByLabelText(/authentication code/i)).toBeInTheDocument();
  });

  it("sends an account with no factor to set one up", async () => {
    statusIs(false);
    const stepUpWithFactor = vi.fn();
    // Routed, because the way out of this branch is a link into the app. The
    // listener is attached on mount, so the challenge waits for the router.
    const { router } = renderPage(SecondFactorStepUpDialog, { auth: { stepUpWithFactor } });
    await waitFor(() => {
      expect(router.state.status).toBe("idle");
    });

    fireChallenge();
    await screen.findByRole("dialog");

    // A code box is no use to somebody who has nothing to type into it.
    await waitFor(() => {
      expect(screen.queryByLabelText(/authentication code/i)).not.toBeInTheDocument();
    });
    expect(screen.getByRole("link", { name: /set one up/i })).toHaveAttribute(
      "href",
      "/profile/security"
    );
  });

  it("offers both ways on when the status cannot be read", async () => {
    // A failed status query knows nothing, so the form stays for the enrolled
    // majority and the way to get a factor is offered beside it.
    server.use(http.get("/api/v1/auth/totp", () => HttpResponse.error()));
    const { router } = renderPage(SecondFactorStepUpDialog, {
      auth: { stepUpWithFactor: vi.fn() },
    });
    await waitFor(() => {
      expect(router.state.status).toBe("idle");
    });

    fireChallenge();
    await screen.findByRole("dialog");

    expect(await screen.findByLabelText(/authentication code/i)).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.getByRole("link", { name: /set one up/i })).toBeInTheDocument();
    });
  });

  it("opens once when a page's many requests are all refused", async () => {
    statusIs(true);
    renderWithProviders(<SecondFactorStepUpDialog />);

    fireChallenge({ guildId: 4 });
    fireChallenge({ guildId: 4 });
    fireChallenge({ guildId: 4 });

    await screen.findByRole("dialog");
    expect(screen.getAllByRole("dialog")).toHaveLength(1);
  });

  it("dismisses without stepping up", async () => {
    statusIs(true);
    const stepUpWithFactor = vi.fn();
    renderWithProviders(<SecondFactorStepUpDialog />, { auth: { stepUpWithFactor } });

    fireChallenge();
    await screen.findByRole("dialog");
    await userEvent.click(screen.getByRole("button", { name: /not now/i }));

    await waitFor(() => {
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    });
    expect(stepUpWithFactor).not.toHaveBeenCalled();
  });
});

describe("SecondFactorStepUpDialog, asked for a passkey", () => {
  it("offers the passkey rather than a code box", async () => {
    passkeysAre([{ id: "pk-1", name: "Laptop" }]);
    renderWithProviders(<SecondFactorStepUpDialog />, { auth: { stepUpWithPasskey: vi.fn() } });

    fireChallenge({ kind: "passkey" });
    await screen.findByRole("dialog");

    expect(await screen.findByRole("button", { name: /use your passkey/i })).toBeInTheDocument();
    expect(screen.queryByLabelText(/authentication code/i)).not.toBeInTheDocument();
  });

  it("adds the passkey to the session already open", async () => {
    passkeysAre([{ id: "pk-1", name: "Laptop" }]);
    const stepUpWithPasskey = vi.fn().mockResolvedValue(undefined);
    renderWithProviders(<SecondFactorStepUpDialog />, { auth: { stepUpWithPasskey } });

    fireChallenge({ kind: "passkey" });
    await screen.findByRole("dialog");
    await userEvent.click(await screen.findByRole("button", { name: /use your passkey/i }));

    await waitFor(() => {
      expect(stepUpWithPasskey).toHaveBeenCalledTimes(1);
    });
    // The page behind it carries on rather than needing a reload.
    await waitFor(() => {
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    });
  });

  it("sends an account holding none to add one", async () => {
    passkeysAre([]);
    const stepUpWithPasskey = vi.fn();
    // Routed, because the way out of this branch is a link into the app.
    const { router } = renderPage(SecondFactorStepUpDialog, { auth: { stepUpWithPasskey } });
    await waitFor(() => {
      expect(router.state.status).toBe("idle");
    });

    fireChallenge({ kind: "passkey" });
    await screen.findByRole("dialog");

    expect(await screen.findByRole("link", { name: /add a passkey/i })).toHaveAttribute(
      "href",
      "/profile/security"
    );
    expect(screen.queryByRole("button", { name: /use your passkey/i })).not.toBeInTheDocument();
  });

  it("keeps the passkey on offer when the account cannot be read", async () => {
    server.use(http.get("/api/v1/auth/passkeys", () => HttpResponse.error()));
    const { router } = renderPage(SecondFactorStepUpDialog, {
      auth: { stepUpWithPasskey: vi.fn() },
    });
    await waitFor(() => {
      expect(router.state.status).toBe("idle");
    });

    fireChallenge({ kind: "passkey" });
    await screen.findByRole("dialog");

    expect(screen.getByRole("button", { name: /use your passkey/i })).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.getByRole("link", { name: /add a passkey/i })).toBeInTheDocument();
    });
  });

  it("says where to present one when the app cannot", async () => {
    const stepUpWithPasskey = vi.fn();
    renderWithProviders(<SecondFactorStepUpDialog />, {
      auth: { stepUpWithPasskey },
      server: { isNativePlatform: true },
    });

    fireChallenge({ kind: "passkey" });
    await screen.findByRole("dialog");

    expect(screen.getByText(/open it in a browser/i)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /use your passkey/i })).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /not now/i }));
    await waitFor(() => {
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    });
    expect(stepUpWithPasskey).not.toHaveBeenCalled();
  });
});
