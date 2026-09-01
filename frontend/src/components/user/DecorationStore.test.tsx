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

const pack = (id: string, installed = false) => ({
  id,
  installed,
  contents: [
    { id: `${id}.dicetower`, kind: "banner", source: id },
    { id: `${id}.natural20`, kind: "frame", source: id },
    { id: `${id}.d20`, kind: "badge", source: id },
  ],
});

const ttrpg = (installed = false) => ({
  id: "ttrpg",
  installed,
  contents: [
    { id: "ttrpg.dicetower", kind: "banner", source: "ttrpg" },
    { id: "ttrpg.natural20", kind: "frame", source: "ttrpg" },
    { id: "ttrpg.d20", kind: "badge", source: "ttrpg" },
  ],
});

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

    expect(await screen.findByRole("heading", { name: "Tabletop" })).toBeInTheDocument();
    expect(screen.getByText(/rolls for it/)).toBeInTheDocument();
  });

  it("takes a pack when asked", async () => {
    render();

    await userEvent.click(await screen.findByRole("button", { name: "Get this pack" }));

    expect(installMutate).toHaveBeenCalledWith("ttrpg");
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
    answerWith([ttrpg(), pack("studio.unknown")]);
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
