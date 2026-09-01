/**
 * The store offers packs, and taking one is what puts its pieces in reach.
 *
 * What is worth pinning here is the tolerance: the server decides what packs
 * exist, and a build with no artwork for one must leave it out rather than
 * draw an empty card.
 */
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { buildUser } from "@/__tests__/factories";
import { renderWithProviders } from "@/__tests__/helpers/render";

import { DecorationStore } from "./DecorationStore";

const mocks = vi.hoisted(() => ({ packs: vi.fn(), install: vi.fn() }));

vi.mock("@/hooks/useUsers", () => ({
  useDecorationPacks: () => mocks.packs(),
  useInstallDecorationPack: (options: unknown) => mocks.install(options),
}));

const listing = (
  uid: string,
  { installed = false, ids = ["ttrpg.dicetower", "ttrpg.natural20", "ttrpg.d20"] } = {}
) => ({
  uid,
  public_id: "core.tabletop",
  name: "Tabletop",
  publisher: "Initiative",
  description: "Dice, and the people who roll them.",
  avatar_url: null,
  installed,
  contents: [
    { id: ids[0], kind: "banner", name: "Dice tower", source: uid },
    { id: ids[1], kind: "frame", name: "Natural 20", source: uid },
    { id: ids[2], kind: "badge", name: "d20", source: uid },
  ],
});

const ttrpg = (installed = false) => listing("PACKTABTP00001", { installed });

const answerWith = (items: unknown[]) =>
  mocks.packs.mockReturnValue({ data: { items }, isLoading: false });

const installMutate = vi.fn();

beforeEach(() => {
  vi.clearAllMocks();
  mocks.install.mockReturnValue({ mutate: installMutate, isPending: false, variables: undefined });
  answerWith([ttrpg()]);
});

const render = () => renderWithProviders(<DecorationStore user={buildUser()} />);

describe("the decoration store", () => {
  it("shows a pack by its name and what it is for", async () => {
    render();

    // The words are the listing's — its publisher named it, and nobody else
    // can name a pack published tomorrow.
    expect(await screen.findByRole("heading", { name: "Tabletop" })).toBeInTheDocument();
    expect(screen.getByText("Dice, and the people who roll them.")).toBeInTheDocument();
  });

  it("takes a pack when asked", async () => {
    render();

    await userEvent.click(await screen.findByRole("button", { name: "Get this pack" }));

    expect(installMutate).toHaveBeenCalledWith("PACKTABTP00001");
  });

  it("marks a pack already held rather than offering it again", async () => {
    // Getting and giving back are never the same button in the same place:
    // the way out lives with the packs you have.
    answerWith([ttrpg(true)]);
    render();

    expect(await screen.findByText("In your collection")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Get this pack" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Give back" })).not.toBeInTheDocument();
  });

  it("leaves out a pack this build has no artwork for", async () => {
    // A later catalog, an older client. An empty card would be worse than none.
    answerWith([
      ttrpg(),
      listing("PACKUNKNWN0001", {
        ids: ["studio.a", "studio.b", "studio.c"],
      }),
    ]);
    render();

    await screen.findByRole("heading", { name: "Tabletop" });
    expect(screen.getAllByRole("listitem")).toHaveLength(1);
  });

  it("says so when the build ships no packs at all", async () => {
    answerWith([]);
    render();

    await waitFor(() => expect(screen.getByText("No packs in this build.")).toBeInTheDocument());
  });
});
