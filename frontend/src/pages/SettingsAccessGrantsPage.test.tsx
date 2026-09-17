import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { buildUser } from "@/__tests__/factories";
import { renderWithProviders } from "@/__tests__/helpers/render";

const createRequest = vi.fn();
const breakGlass = vi.fn();

// Partial: the page also reaches for the page-flattening helper.
vi.mock(import("@/hooks/useAccessGrants"), async (importOriginal) => ({
  ...(await importOriginal()),
  useMyAccessGrants: () => ({ data: { pages: [] }, isLoading: false }),
  usePendingAccessGrants: () => ({ data: { pages: [] }, isLoading: false }),
  useCreateAccessRequest: () => ({ mutate: createRequest, isPending: false }),
  useCancelAccessRequest: () => ({ mutate: vi.fn(), isPending: false }),
  useBreakGlass: () => ({ mutate: breakGlass, isPending: false }),
  useBreakGlassRequirements: () => ({
    data: { second_factor_required: false, enrolled: true },
    refetch: vi.fn(),
  }),
  useApproveAccessGrant: () => ({ mutate: vi.fn(), isPending: false }),
  useDenyAccessGrant: () => ({ mutate: vi.fn(), isPending: false }),
  useRevokeAccessGrant: () => ({ mutate: vi.fn(), isPending: false }),
}));

vi.mock(import("@/hooks/useGuilds"), async (importOriginal) => ({
  ...(await importOriginal()),
  useGuilds: () => ({ refreshGuilds: vi.fn() }),
}));

import { SettingsAccessGrantsPage } from "./SettingsAccessGrantsPage";

const render = () =>
  renderWithProviders(<SettingsAccessGrantsPage />, {
    auth: { user: buildUser({ capabilities: ["access.request"] }) },
  });

describe("SettingsAccessGrantsPage", () => {
  beforeEach(() => {
    createRequest.mockClear();
    breakGlass.mockClear();
  });

  it("asks for content by default, at a content rung", async () => {
    const user = userEvent.setup();
    render();

    await user.type(await screen.findByLabelText(/community id/i), "7");
    await user.type(screen.getByLabelText(/reason/i), "looking into a report");
    await user.click(screen.getByRole("button", { name: /request access/i }));

    expect(createRequest).toHaveBeenCalledTimes(1);
    expect(createRequest.mock.calls[0][0]).toMatchObject({
      guild_id: 7,
      purpose: "content",
      access_level: "read",
    });
    expect(createRequest.mock.calls[0][0].settings_level).toBeUndefined();
  });

  it("sends a settings rung, and no content level, for a settings request", async () => {
    const user = userEvent.setup();
    render();

    await user.click(await screen.findByLabelText(/what for/i));
    await user.click(await screen.findByRole("option", { name: /settings/i }));
    await user.click(screen.getByLabelText(/level/i));
    await user.click(await screen.findByRole("option", { name: /^superadmin$/i }));

    await user.type(screen.getByLabelText(/community id/i), "7");
    await user.type(screen.getByLabelText(/reason/i), "billing question");
    await user.click(screen.getByRole("button", { name: /request access/i }));

    expect(createRequest.mock.calls[0][0]).toMatchObject({
      purpose: "settings",
      settings_level: "superadmin",
    });
    expect(createRequest.mock.calls[0][0].access_level).toBeUndefined();
  });
});
