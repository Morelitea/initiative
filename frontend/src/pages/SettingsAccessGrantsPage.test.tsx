import type {
  InfiniteData,
  UseInfiniteQueryResult,
  UseMutationResult,
  UseQueryResult,
} from "@tanstack/react-query";
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { buildUser } from "@/__tests__/factories";
import { renderWithProviders } from "@/__tests__/helpers/render";

const createRequest = vi.fn();
const breakGlass = vi.fn();
/** The ceiling the server reports for the caller's requests. */
let requestCeiling = 240;

/** What every read the page makes has come back as: loaded, nothing in flight. */
const settled = {
  dataUpdatedAt: 0,
  error: null,
  errorUpdatedAt: 0,
  failureCount: 0,
  failureReason: null,
  errorUpdateCount: 0,
  isError: false,
  isFetched: true,
  isFetchedAfterMount: true,
  isFetching: false,
  isLoading: false,
  isPending: false,
  isLoadingError: false,
  isInitialLoading: false,
  isPaused: false,
  isPlaceholderData: false,
  isRefetchError: false,
  isRefetching: false,
  isStale: false,
  isSuccess: true,
  isEnabled: true,
  status: "success",
  fetchStatus: "idle",
} as const;

/** A read that answered with this. */
const answered = <TData,>(data: TData): UseQueryResult<TData, Error> => ({
  ...settled,
  data,
  refetch: vi.fn(),
});

/** A paged list that answered with no pages at all. */
const noPages = <TPage,>(): UseInfiniteQueryResult<InfiniteData<TPage, number>, Error> => ({
  ...settled,
  data: { pages: [], pageParams: [] },
  refetch: vi.fn(),
  fetchNextPage: vi.fn(),
  fetchPreviousPage: vi.fn(),
  hasNextPage: false,
  hasPreviousPage: false,
  isFetchNextPageError: false,
  isFetchingNextPage: false,
  isFetchPreviousPageError: false,
  isFetchingPreviousPage: false,
});

/** A mutation nobody has fired yet. */
const idle = <TData, TVariables>(
  mutate: UseMutationResult<TData, Error, TVariables>["mutate"] = vi.fn<
    (...args: unknown[]) => void
  >()
): UseMutationResult<TData, Error, TVariables> => ({
  data: undefined,
  variables: undefined,
  error: null,
  context: undefined,
  failureCount: 0,
  failureReason: null,
  isError: false,
  isIdle: true,
  isPending: false,
  isPaused: false,
  isSuccess: false,
  status: "idle",
  submittedAt: 0,
  mutate,
  mutateAsync: vi.fn<(...args: unknown[]) => Promise<TData>>(),
  reset: vi.fn(),
});

// Partial: the page also reaches for the page-flattening helper.
vi.mock(import("@/hooks/useAccessGrants"), async (importOriginal) => ({
  ...(await importOriginal()),
  useMyAccessGrants: () => noPages(),
  useAccessGrantQueue: () => noPages(),
  useAccessGrantLimits: () => answered({ max_duration_minutes: requestCeiling }),
  useCreateAccessRequest: () => idle(createRequest),
  useCancelAccessRequest: () => idle(),
  useBreakGlass: () => idle(breakGlass),
  useBreakGlassRequirements: () =>
    answered({
      second_factor_required: false,
      max_duration_minutes: 240,
      totp_enrolled: true,
      passkey_enrolled: false,
    }),
  useApproveAccessGrant: () => idle(),
  useDenyAccessGrant: () => idle(),
  useRevokeAccessGrant: () => idle(),
}));

vi.mock(import("@/hooks/useGuilds"), async (importOriginal) => ({
  ...(await importOriginal()),
  useGuilds: () => ({
    guilds: [],
    activeGuild: null,
    activeGuildId: null,
    activeGuildReadOnly: false,
    loading: false,
    error: null,
    refreshGuilds: vi.fn(),
    switchGuild: vi.fn(),
    syncGuildFromUrl: vi.fn(),
    createGuild: vi.fn(),
    updateGuildInState: vi.fn(),
    reorderGuilds: vi.fn(),
    canCreateGuilds: false,
  }),
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
    requestCeiling = 240;
  });

  it("asks for a content read and no settings by default", async () => {
    const user = userEvent.setup();
    render();

    await user.type(await screen.findByLabelText(/community id/i), "7");
    await user.type(screen.getByLabelText(/reason/i), "looking into a report");
    await user.click(screen.getByRole("button", { name: /request access/i }));

    expect(createRequest).toHaveBeenCalledTimes(1);
    expect(createRequest.mock.calls[0][0]).toMatchObject({
      guild_id: 7,
      access_level: "read",
      requested_duration_minutes: 240,
    });
    expect(createRequest.mock.calls[0][0].settings_level).toBeUndefined();
  });

  it("offers the windows up to the ceiling the server reports", async () => {
    requestCeiling = 480;
    const user = userEvent.setup();
    render();

    await user.click(await screen.findByLabelText(/duration/i));

    expect(await screen.findByRole("option", { name: /^8 hours$/i })).toBeInTheDocument();
    expect(screen.queryByRole("option", { name: /^24 hours$/i })).not.toBeInTheDocument();
  });

  it("offers a ceiling the deployment set between the presets", async () => {
    requestCeiling = 120;
    const user = userEvent.setup();
    render();

    await user.click(await screen.findByLabelText(/duration/i));
    await user.click(await screen.findByRole("option", { name: /^2 hours$/i }));
    expect(screen.queryByRole("option", { name: /^4 hours$/i })).not.toBeInTheDocument();

    await user.type(screen.getByLabelText(/community id/i), "7");
    await user.type(screen.getByLabelText(/reason/i), "a short look");
    await user.click(screen.getByRole("button", { name: /request access/i }));

    expect(createRequest.mock.calls[0][0]).toMatchObject({ requested_duration_minutes: 120 });
  });

  it("asks for both where the errand needs both", async () => {
    const user = userEvent.setup();
    render();

    await user.click(await screen.findByLabelText(/content access/i));
    await user.click(await screen.findByRole("option", { name: /read & write/i }));
    await user.click(screen.getByLabelText(/settings access/i));
    await user.click(await screen.findByRole("option", { name: /^superadmin$/i }));

    await user.type(screen.getByLabelText(/community id/i), "7");
    await user.type(screen.getByLabelText(/reason/i), "clearing up an incident");
    await user.click(screen.getByRole("button", { name: /request access/i }));

    expect(createRequest.mock.calls[0][0]).toMatchObject({
      access_level: "read_write",
      settings_level: "superadmin",
    });
  });

  it("can ask for settings alone", async () => {
    const user = userEvent.setup();
    render();

    await user.click(await screen.findByLabelText(/content access/i));
    await user.click(await screen.findByRole("option", { name: /^none$/i }));
    await user.click(screen.getByLabelText(/settings access/i));
    await user.click(await screen.findByRole("option", { name: /^admin$/i }));

    await user.type(screen.getByLabelText(/community id/i), "7");
    await user.type(screen.getByLabelText(/reason/i), "billing question");
    await user.click(screen.getByRole("button", { name: /request access/i }));

    expect(createRequest.mock.calls[0][0]).toMatchObject({ settings_level: "admin" });
    expect(createRequest.mock.calls[0][0].access_level).toBeUndefined();
  });

  it("will not send a request that asks for nothing", async () => {
    const user = userEvent.setup();
    render();

    await user.click(await screen.findByLabelText(/content access/i));
    await user.click(await screen.findByRole("option", { name: /^none$/i }));

    await user.type(screen.getByLabelText(/community id/i), "7");
    await user.type(screen.getByLabelText(/reason/i), "nothing in particular");

    expect(screen.getByRole("button", { name: /request access/i })).toBeDisabled();
    expect(
      screen.getByText(/choose content access, settings access, or both/i)
    ).toBeInTheDocument();
    expect(createRequest).not.toHaveBeenCalled();
  });
});
