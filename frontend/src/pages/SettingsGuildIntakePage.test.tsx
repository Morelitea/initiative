/**
 * The operations community's intake (Community settings → Intake).
 *
 * A stream that has never been set up offers both ways of setting one up
 * rather than only the blueprint; a community that is not the operations
 * community is told so rather than shown an empty page; and the page is the
 * seat's.
 */
import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { AxiosError, AxiosHeaders } from "axios";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { buildGuild, buildUser } from "@/__tests__/factories";
import { renderWithProviders } from "@/__tests__/helpers/render";
import type { GuildRole } from "@/api/generated/initiativeAPI.schemas";
import type { GuildEntry } from "@/hooks/useGuilds";

const importMutate = vi.fn();
const upsertMutate = vi.fn();
const deleteMutate = vi.fn();

const state = vi.hoisted(() => ({
  guildRole: "superadmin" as GuildRole,
  bindings: [] as Array<Record<string, unknown>>,
  error: null as unknown,
  optionsError: false,
  isFetching: false,
}));

const unbound = (stream: string) => ({
  stream,
  binding_id: null,
  project_id: null,
  project_name: null,
  initiative_id: null,
  initiative_name: null,
  default_status_id: null,
  default_status_name: null,
  enabled: false,
  last_case_at: null,
  project_archived: false,
});

const STREAMS = ["security", "moderation", "support", "feedback"];

const notFound = () =>
  new AxiosError("Not Found", "ERR_BAD_REQUEST", undefined, undefined, {
    status: 404,
    statusText: "Not Found",
    headers: {},
    config: { headers: new AxiosHeaders() },
    data: { detail: "INTAKE_NOT_OPERATIONS_GUILD" },
  });

vi.mock("@/hooks/useGuildIntake", () => ({
  useGuildIntake: () => ({
    data: state.error ? undefined : { bindings: state.bindings },
    isSuccess: !state.error,
    isFetching: state.isFetching,
    isError: Boolean(state.error),
    error: state.error,
    refetch: vi.fn(),
  }),
  useGuildIntakeOptions: () => ({
    isFetching: false,
    isError: state.optionsError,
    refetch: vi.fn(),
    data: {
      initiatives: [
        {
          id: 7,
          name: "Trust and Safety",
          projects: [
            {
              id: 21,
              name: "Security",
              statuses: [
                { id: 31, name: "Triage" },
                { id: 32, name: "Confirmed" },
              ],
            },
          ],
        },
      ],
    },
  }),
  useUpsertIntakeBinding: () => ({ mutate: upsertMutate, isPending: false }),
  useImportIntakeBlueprint: () => ({ mutate: importMutate, isPending: false }),
  useDeleteIntakeBinding: () => ({ mutate: deleteMutate, isPending: false }),
}));

// Partial: the render helper reaches for ``GuildContext`` from this module.
vi.mock(import("@/hooks/useGuilds"), async (importOriginal) => ({
  ...(await importOriginal()),
  useGuilds: () => {
    const activeGuild: GuildEntry = buildGuild({
      id: 4,
      name: "Operations",
      role: state.guildRole,
    });
    return {
      guilds: [activeGuild],
      activeGuild,
      activeGuildId: 4,
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
    };
  },
}));

vi.mock("@/hooks/useActiveGuildId", () => ({ useActiveGuildId: () => 4 }));

import { SettingsGuildIntakePage } from "./SettingsGuildIntakePage";

const render = () =>
  renderWithProviders(<SettingsGuildIntakePage />, { auth: { user: buildUser() } });

describe("SettingsGuildIntakePage", () => {
  beforeEach(() => {
    importMutate.mockClear();
    upsertMutate.mockClear();
    deleteMutate.mockClear();
    state.guildRole = "superadmin";
    state.bindings = STREAMS.map(unbound);
    state.error = null;
    state.optionsError = false;
    state.isFetching = false;
  });

  it("lists every stream, bound or not", () => {
    render();
    for (const title of ["Security", "Moderation", "Support", "Feedback"]) {
      expect(screen.getByRole("region", { name: title })).toBeInTheDocument();
    }
    expect(screen.getAllByText("Not set up")).toHaveLength(STREAMS.length);
  });

  it("sets a stream up from its blueprint", async () => {
    render();
    const user = userEvent.setup();

    // Each stream's card is a region named after the stream, so "the security
    // one" is unambiguous without reaching into the DOM.
    const card = screen.getByRole("region", { name: "Security" });
    const setUp = () => within(card).getByRole("button", { name: "Set this up for me" });

    // Disabled until an initiative is chosen: the import has to land somewhere.
    expect(setUp()).toBeDisabled();
    await user.click(within(card).getByRole("combobox", { name: "Initiative" }));
    await user.click(await screen.findByRole("option", { name: "Trust and Safety" }));
    await user.click(setUp());

    expect(importMutate).toHaveBeenCalledWith({ stream: "security", initiativeId: 7 });
  });

  it("shows where a bound stream lands and when it last opened a case", () => {
    state.bindings = [
      {
        ...unbound("security"),
        binding_id: 1,
        project_id: 21,
        project_name: "Security",
        initiative_id: 7,
        initiative_name: "Trust and Safety",
        default_status_id: 31,
        default_status_name: "Triage",
        enabled: true,
        last_case_at: "2026-09-15T10:00:00Z",
      },
      ...STREAMS.slice(1).map(unbound),
    ];
    render();

    expect(screen.getByText("Receiving")).toBeInTheDocument();
    expect(screen.getByText(/Last case opened/)).toBeInTheDocument();
  });

  it("says a stream whose project was archived receives nothing", () => {
    state.bindings = [
      {
        ...unbound("security"),
        binding_id: 1,
        project_id: 99,
        project_name: "Old Security",
        initiative_id: 7,
        initiative_name: "Trust and Safety",
        enabled: true,
        project_archived: true,
      },
      ...STREAMS.slice(1).map(unbound),
    ];
    render();

    const card = screen.getByRole("region", { name: "Security" });
    expect(within(card).getByText("Destination archived")).toBeInTheDocument();
    expect(within(card).queryByText("Receiving")).not.toBeInTheDocument();
  });

  it("offers no destination while the reads are in flight", () => {
    state.isFetching = true;
    render();

    const card = screen.getByRole("region", { name: "Security" });
    expect(within(card).getByRole("button", { name: "Set this up for me" })).toBeDisabled();
  });

  it("says so when this is not the operations community", () => {
    state.error = notFound();
    render();

    expect(
      screen.getByText(
        "This community doesn't receive this deployment's operations work, so it has no intake to set up."
      )
    ).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Security" })).not.toBeInTheDocument();
  });

  it("says the read failed rather than showing an unconfigured community", () => {
    state.optionsError = true;
    render();

    expect(screen.getByText("Could not load these settings")).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Security" })).not.toBeInTheDocument();
  });

  it("is the seat's", () => {
    state.guildRole = "admin";
    render();

    expect(
      screen.getByText("Only this community's superadmin can set up where operations work lands.")
    ).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Security" })).not.toBeInTheDocument();
  });
});
