import { fireEvent, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { renderWithProviders } from "@/__tests__/helpers/render";
import type { PlatformAuthSettingsResponse } from "@/api/generated/initiativeAPI.schemas";

const methodsMutate = vi.fn();
const scopeMutate = vi.fn();

let settings: PlatformAuthSettingsResponse;

vi.mock("@/hooks/useSettings", () => ({
  usePlatformAuthSettings: () => ({ data: settings, isLoading: false }),
  useUpdateLoginMethods: () => ({ mutate: methodsMutate, isPending: false }),
  useUpdateAuthScope: () => ({ mutate: scopeMutate, isPending: false }),
}));

import { PlatformAuthSection } from "./PlatformAuthSection";

const base: PlatformAuthSettingsResponse = {
  auth_scope: "platform",
  auth_scope_from_env: true,
  methods: [
    { method: "password", enabled: true, would_strand: 0 },
    { method: "sso", enabled: true, would_strand: 0 },
  ],
  guilds_requiring_sign_in: 0,
  platform_switch_would_strand: 0,
};

describe("PlatformAuthSection", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    settings = structuredClone(base);
  });

  it("withdraws a method nobody depends on without asking", () => {
    renderWithProviders(<PlatformAuthSection />);

    fireEvent.click(screen.getByLabelText("Single sign-on"));

    expect(methodsMutate).toHaveBeenCalledWith({ methods: ["password"] });
  });

  it("asks before withdrawing a method that is somebody's only way in", () => {
    settings.methods = [
      { method: "password", enabled: true, would_strand: 0 },
      { method: "sso", enabled: true, would_strand: 3 },
    ];
    renderWithProviders(<PlatformAuthSection />);

    fireEvent.click(screen.getByLabelText("Single sign-on"));
    expect(methodsMutate).not.toHaveBeenCalled();

    // The dialog names the number, and acknowledging sends that same number.
    expect(
      screen.getByText(/3 accounts sign in only this way and will not be able/)
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Withdraw" }));

    expect(methodsMutate).toHaveBeenCalledWith({
      methods: ["password"],
      acknowledge_stranded: 3,
    });
  });

  it("will not let the last way in be withdrawn", () => {
    settings.methods = [
      { method: "password", enabled: true, would_strand: 0 },
      { method: "sso", enabled: false, would_strand: 0 },
    ];
    renderWithProviders(<PlatformAuthSection />);

    expect(screen.getByLabelText("Password")).toBeDisabled();
  });

  it("says when the posture is the deployment's rather than a choice", () => {
    renderWithProviders(<PlatformAuthSection />);

    expect(screen.getByText("Set at deployment")).toBeInTheDocument();
  });

  it("confirms a posture change before sending it", () => {
    renderWithProviders(<PlatformAuthSection />);

    fireEvent.click(screen.getByLabelText("Per-community sign-in"));
    expect(scopeMutate).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "Change" }));
    expect(scopeMutate).toHaveBeenCalledWith({ auth_scope: "guild" });
  });

  it("offers no posture choice when single sign-on is not permitted", () => {
    settings.methods = [
      { method: "password", enabled: true, would_strand: 0 },
      { method: "sso", enabled: false, would_strand: 0 },
    ];
    renderWithProviders(<PlatformAuthSection />);

    expect(screen.getByLabelText("Platform-wide sign-in")).toBeDisabled();
    expect(screen.getByText(/does not permit single sign-on/)).toBeInTheDocument();
  });
});
