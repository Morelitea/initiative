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

const fireChallenge = (guildId: number | null = 4) => {
  act(() => {
    window.dispatchEvent(new CustomEvent(AUTH_FACTOR_REQUIRED_EVENT, { detail: { guildId } }));
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

  it("opens once when a page's many requests are all refused", async () => {
    statusIs(true);
    renderWithProviders(<SecondFactorStepUpDialog />);

    fireChallenge(4);
    fireChallenge(4);
    fireChallenge(4);

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
