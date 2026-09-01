/**
 * The profile tab shows you what you are about to be.
 *
 * The card at the top is the same one strangers see, so what is worth pinning
 * is that it is complete — the badges and the status are on it, not only the
 * picture — and that it follows the drafts below rather than what is saved.
 */
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { buildOwnedDecoration, buildUser } from "@/__tests__/factories";
import { renderPage } from "@/__tests__/helpers/render";

import { UserSettingsProfilePage } from "./UserSettingsProfilePage";

const mocks = vi.hoisted(() => ({ library: vi.fn(), update: vi.fn(), packs: vi.fn() }));

vi.mock("@/hooks/useUsers", () => ({
  useMyDecorations: () => mocks.library(),
  useUpdateCurrentUser: (options: unknown) => mocks.update(options),
  useDecorationPacks: () => mocks.packs(),
  useRemoveDecorationPack: () => ({ mutate: vi.fn(), isPending: false, variables: undefined }),
}));

const user = buildUser({
  username: "jordan",
  discriminator: 1234,
  custom_status: { emoji: "🎲", text: "Rolling initiative" },
  profile_decorations: { banner: null, frame: "core.gold", badges: ["core.founder"] },
});

beforeEach(() => {
  vi.clearAllMocks();
  mocks.update.mockReturnValue({ mutate: vi.fn(), isPending: false });
  mocks.packs.mockReturnValue({ data: { items: [] }, isLoading: false });
  mocks.library.mockReturnValue({
    data: {
      items: [
        buildOwnedDecoration({ id: "core.founder", kind: "badge" }),
        buildOwnedDecoration({ id: "core.storyteller", kind: "badge" }),
        buildOwnedDecoration({ id: "core.aurora", kind: "banner" }),
      ],
    },
  });
});

const render = () =>
  renderPage(() => <UserSettingsProfilePage user={user} refreshUser={() => Promise.resolve()} />);

describe("the profile preview", () => {
  it("shows the whole profile, not just the picture", async () => {
    render();

    // The handle, the status and the badge a stranger would see.
    expect(await screen.findByText("jordan")).toBeInTheDocument();
    expect(screen.getByText("Rolling initiative")).toBeInTheDocument();
    expect(screen.getByRole("img", { name: "Founder" })).toBeInTheDocument();
  });

  it("follows what is picked, before it is saved", async () => {
    render();

    await userEvent.click(await screen.findByRole("checkbox", { name: "Storyteller" }));

    expect(screen.getByRole("img", { name: "Storyteller" })).toBeInTheDocument();
  });
});
