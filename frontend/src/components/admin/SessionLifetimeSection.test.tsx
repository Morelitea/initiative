import { fireEvent, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { renderWithProviders } from "@/__tests__/helpers/render";
import type { PlatformAuthSettingsResponse } from "@/api/generated/initiativeAPI.schemas";

let settings: PlatformAuthSettingsResponse;

const lifetimeMutate = vi.fn();

vi.mock("@/hooks/useSettings", () => ({
  usePlatformAuthSettings: () => ({ data: settings, isLoading: false }),
  useUpdateSessionLifetime: () => ({ mutate: lifetimeMutate, isPending: false }),
}));

import { SessionLifetimeSection } from "./SessionLifetimeSection";

const base: PlatformAuthSettingsResponse = {
  methods: [
    { method: "password", enabled: true, would_strand: 0 },
    { method: "sso", enabled: true, would_strand: 0 },
  ],
  guilds_requiring_sign_in: 0,
  session_max_hours: null,
  second_factor_requirement: "nobody",
  accounts_without_factor: { platform_roles: 0, everyone: 0 },
};

describe("SessionLifetimeSection", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    settings = structuredClone(base);
  });

  it("starts blank when the deployment asks for no limit", () => {
    settings = { ...base, session_max_hours: null };
    renderWithProviders(<SessionLifetimeSection />);

    expect(screen.getByLabelText(/hours/i)).toHaveValue(null);
  });

  it("saves a session limit", () => {
    settings = { ...base, session_max_hours: null };
    renderWithProviders(<SessionLifetimeSection />);

    fireEvent.change(screen.getByLabelText(/hours/i), { target: { value: "12" } });
    fireEvent.click(screen.getByRole("button", { name: /save/i }));

    expect(lifetimeMutate).toHaveBeenCalledWith({ session_max_hours: 12 });
  });

  it("clears the limit when the field is emptied", () => {
    settings = { ...base, session_max_hours: 12 };
    renderWithProviders(<SessionLifetimeSection />);

    fireEvent.change(screen.getByLabelText(/hours/i), { target: { value: "" } });
    fireEvent.click(screen.getByRole("button", { name: /save/i }));

    expect(lifetimeMutate).toHaveBeenCalledWith({ session_max_hours: null });
  });

  it("will not save an unchanged limit", () => {
    settings = { ...base, session_max_hours: 12 };
    renderWithProviders(<SessionLifetimeSection />);

    expect(screen.getByRole("button", { name: /save/i })).toBeDisabled();
  });
});
