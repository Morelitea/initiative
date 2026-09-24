import { fireEvent, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { renderWithProviders } from "@/__tests__/helpers/render";
import type { CaptchaSettingsResponse } from "@/api/generated/initiativeAPI.schemas";

let settings: CaptchaSettingsResponse;

const mutate = vi.fn();

vi.mock("@/hooks/useSettings", () => ({
  useCaptchaSettings: () => ({ data: settings, isLoading: false }),
  useUpdateCaptchaSettings: () => ({ mutate, isPending: false }),
}));

import { CaptchaSection } from "./CaptchaSection";

const base: CaptchaSettingsResponse = {
  provider: "turnstile",
  site_key: "site-key",
  has_secret_key: true,
  enforcing: true,
};

describe("CaptchaSection", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    settings = structuredClone(base);
  });

  it("keeps the saved secret when the field is left blank", () => {
    renderWithProviders(<CaptchaSection />);

    fireEvent.change(screen.getByLabelText(/site key/i), { target: { value: "new-site" } });
    fireEvent.click(screen.getByRole("button", { name: /save/i }));

    expect(mutate).toHaveBeenCalledWith(
      { provider: "turnstile", site_key: "new-site" },
      expect.anything()
    );
  });

  it("sends a secret that was typed", () => {
    renderWithProviders(<CaptchaSection />);

    fireEvent.change(screen.getByLabelText(/secret key/i), { target: { value: "s3cret" } });
    fireEvent.click(screen.getByRole("button", { name: /save/i }));

    expect(mutate).toHaveBeenCalledWith(
      { provider: "turnstile", site_key: "site-key", secret_key: "s3cret" },
      expect.anything()
    );
  });

  it("says when a provider is chosen but the captcha is not on", () => {
    settings = { ...base, has_secret_key: false, enforcing: false };
    renderWithProviders(<CaptchaSection />);

    expect(screen.getByText(/comes on once/i)).toBeInTheDocument();
  });
});
