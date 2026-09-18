import { fireEvent, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { renderWithProviders } from "@/__tests__/helpers/render";
import type { PlatformAuthSettingsResponse } from "@/api/generated/initiativeAPI.schemas";

const methodsMutate = vi.fn();

let settings: PlatformAuthSettingsResponse;

const lifetimeMutate = vi.fn();

vi.mock("@/hooks/useSettings", () => ({
  usePlatformAuthSettings: () => ({ data: settings, isLoading: false }),
  useUpdateLoginMethods: () => ({ mutate: methodsMutate, isPending: false }),
  useUpdateSessionLifetime: () => ({ mutate: lifetimeMutate, isPending: false }),
}));

import { PlatformAuthSection } from "./PlatformAuthSection";

const base: PlatformAuthSettingsResponse = {
  methods: [
    { method: "password", enabled: true, would_strand: 0 },
    { method: "sso", enabled: true, would_strand: 0 },
  ],
  guilds_requiring_sign_in: 0,
  session_max_hours: null,
};

describe("PlatformAuthSection", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    settings = structuredClone(base);
  });

  // The ways in are not rendered while SHOW_LOGIN_METHODS is off; these cover
  // the section it hides and come back with it.
  describe.skip("ways in", () => {
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

    it("says when communities still require a sign-in of their own", () => {
      settings.guilds_requiring_sign_in = 2;
      renderWithProviders(<PlatformAuthSection />);

      expect(
        screen.getByText(/2 communities require a sign-in through a provider of their own/)
      ).toBeInTheDocument();
    });

    it("will not let the last way in be withdrawn", () => {
      settings.methods = [
        { method: "password", enabled: true, would_strand: 0 },
        { method: "sso", enabled: false, would_strand: 0 },
      ];
      renderWithProviders(<PlatformAuthSection />);

      expect(screen.getByLabelText("Password")).toBeDisabled();
    });
  });

  it("starts blank when the deployment asks for no limit", () => {
    settings = { ...base, session_max_hours: null };
    renderWithProviders(<PlatformAuthSection />);

    expect(screen.getByLabelText(/hours/i)).toHaveValue(null);
  });

  it("saves a session limit", () => {
    settings = { ...base, session_max_hours: null };
    renderWithProviders(<PlatformAuthSection />);

    fireEvent.change(screen.getByLabelText(/hours/i), { target: { value: "12" } });
    fireEvent.click(screen.getByRole("button", { name: /save/i }));

    expect(lifetimeMutate).toHaveBeenCalledWith({ session_max_hours: 12 });
  });

  it("clears the limit when the field is emptied", () => {
    settings = { ...base, session_max_hours: 12 };
    renderWithProviders(<PlatformAuthSection />);

    fireEvent.change(screen.getByLabelText(/hours/i), { target: { value: "" } });
    fireEvent.click(screen.getByRole("button", { name: /save/i }));

    expect(lifetimeMutate).toHaveBeenCalledWith({ session_max_hours: null });
  });

  it("will not save an unchanged limit", () => {
    settings = { ...base, session_max_hours: 12 };
    renderWithProviders(<PlatformAuthSection />);

    expect(screen.getByRole("button", { name: /save/i })).toBeDisabled();
  });
});
