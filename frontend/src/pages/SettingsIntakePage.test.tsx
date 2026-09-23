/**
 * The owner's intake settings: which community receives operations work, and
 * who to contact.
 *
 * Which project each stream lands in is the community's own setting, so this
 * page offers nothing to bind: it names the community, says which streams it
 * currently receives, and links to where its superadmin sets them up.
 */
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { buildUser } from "@/__tests__/factories";
import { renderPage } from "@/__tests__/helpers/render";

const guildMutate = vi.fn();
const generalContactMutate = vi.fn();
const streamContactMutate = vi.fn();

const state = vi.hoisted(() => ({
  operationsGuildId: null as number | null,
  receiving: [] as string[],
  isError: false,
  isFetching: false,
  generalContact: null as string | null,
  contactEmails: {} as Record<string, string>,
}));

vi.mock("@/hooks/useIntakeSettings", () => ({
  useIntakeSettings: () => ({
    data: state.isError
      ? undefined
      : {
          operations_guild_id: state.operationsGuildId,
          operations_guild_name: state.operationsGuildId ? "Operations" : null,
          receiving: state.receiving,
          general_contact_email: state.generalContact,
          contact_emails: state.contactEmails,
        },
    isLoading: false,
    isFetching: state.isFetching,
    isError: state.isError,
    refetch: vi.fn(),
  }),
  useUpdateOperationsGuild: () => ({ mutate: guildMutate, isPending: false }),
  useUpdateIntakeGeneralContact: () => ({ mutateAsync: generalContactMutate, isPending: false }),
  useUpdateIntakeStreamContact: () => ({ mutateAsync: streamContactMutate, isPending: false }),
}));

vi.mock("@/hooks/useSettings", () => ({
  usePlatformGuilds: () => ({ data: [{ id: 3, name: "Operations" }] }),
}));

import { SettingsIntakePage } from "./SettingsIntakePage";

const render = (role: "owner" | "operator" = "owner") =>
  renderPage(SettingsIntakePage, { auth: { user: buildUser({ role }) } });

describe("SettingsIntakePage", () => {
  beforeEach(() => {
    guildMutate.mockClear();
    generalContactMutate.mockReset().mockResolvedValue({});
    streamContactMutate.mockReset().mockResolvedValue({});
    state.generalContact = null;
    state.contactEmails = {};
    state.operationsGuildId = null;
    state.receiving = [];
    state.isError = false;
    state.isFetching = false;
  });

  it("names no streams until a community is named", async () => {
    render();
    expect(await screen.findByRole("combobox", { name: "Community" })).toBeInTheDocument();
    expect(screen.queryByText("Receiving")).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /intake settings/ })).not.toBeInTheDocument();
  });

  it("says which streams the named community receives, and links to where they are set up", async () => {
    state.operationsGuildId = 3;
    state.receiving = ["security"];
    render();

    expect(await screen.findByText("Receiving")).toBeInTheDocument();
    expect(screen.getAllByText("Not receiving")).toHaveLength(3);
    expect(
      screen.getByText(
        "Operations's superadmin sets which project each stream lands in, under Community settings › Intake."
      )
    ).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open Operations's intake settings" })).toHaveAttribute(
      "href",
      "/c/3/settings/intake"
    );
    // Nothing to bind here: that is the community's own page.
    expect(screen.queryByRole("button", { name: "Set this up for me" })).not.toBeInTheDocument();
  });

  it("tells a non-owner this is not theirs to configure", async () => {
    render("operator");
    expect(
      await screen.findByText("Only platform owners can configure where operations work lands.")
    ).toBeInTheDocument();
  });

  it("says the read failed rather than showing an unconfigured deployment", async () => {
    // The page shows the failure and withholds the picker, so a change is only
    // made against a value that was actually read.
    state.isError = true;
    state.operationsGuildId = 3;
    render();

    expect(await screen.findByText("Could not load these settings")).toBeInTheDocument();
    expect(screen.queryByRole("combobox", { name: "Community" })).not.toBeInTheDocument();
  });

  it("holds the picker while the read is in flight", async () => {
    state.operationsGuildId = 3;
    state.isFetching = true;
    render();

    expect(await screen.findByRole("combobox", { name: "Community" })).toBeDisabled();
  });

  it("says who to contact before any community is named", async () => {
    state.generalContact = "ops@example.com";
    state.contactEmails = { moderation: "trust@example.com" };
    render();
    const user = userEvent.setup();

    const general = await screen.findByLabelText("General contact");
    expect(general).toHaveValue("ops@example.com");
    expect(screen.getByLabelText("Moderation")).toHaveValue("trust@example.com");
    expect(screen.getByLabelText("Support")).toHaveValue("");

    const save = screen.getByRole("button", { name: "Save contacts" });
    expect(save).toBeDisabled();

    await user.type(screen.getByLabelText("Support"), "help@example.com");
    await user.clear(screen.getByLabelText("Moderation"));
    await user.click(save);

    expect(generalContactMutate).not.toHaveBeenCalled();
    expect(streamContactMutate).toHaveBeenCalledWith({
      stream: "moderation",
      body: { email: null },
    });
    expect(streamContactMutate).toHaveBeenCalledWith({
      stream: "support",
      body: { email: "help@example.com" },
    });
  });
});
