/**
 * The packs you have: what each gave you, and the way out.
 *
 * This is the half of the store that answers "what do I have" — so what is
 * worth pinning is that it shows only downloaded packs, names their pieces,
 * and is the one place removal happens.
 */
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { renderWithProviders } from "@/__tests__/helpers/render";

import { MyDecorationPacks } from "./MyDecorationPacks";

const mocks = vi.hoisted(() => ({ packs: vi.fn(), remove: vi.fn() }));

vi.mock("@/hooks/useUsers", () => ({
  useDecorationPacks: () => mocks.packs(),
  useRemoveDecorationPack: (options: unknown) => mocks.remove(options),
}));

const entry = (uid: string, installed: boolean, { name = "Tabletop", slug = "ttrpg" } = {}) => ({
  uid,
  public_id: `core.${slug}`,
  name,
  publisher: "Initiative",
  description: "Dice, and the people who roll them.",
  avatar_url: null,
  installed,
  contents: [
    { id: `${slug}.dicetower`, kind: "banner", name: "Dice tower", source: uid },
    { id: `${slug}.natural20`, kind: "frame", name: "Natural 20", source: uid },
    { id: `${slug}.d20`, kind: "badge", name: "d20", source: uid },
  ],
});

const answerWith = (items: unknown[]) =>
  mocks.packs.mockReturnValue({ data: { items }, isLoading: false });

const removeMutate = vi.fn();

beforeEach(() => {
  vi.clearAllMocks();
  mocks.remove.mockReturnValue({ mutate: removeMutate, isPending: false, variables: undefined });
});

describe("the packs you have", () => {
  it("lists a downloaded pack and names its pieces", async () => {
    answerWith([entry("PACKTABTP00001", true)]);
    renderWithProviders(<MyDecorationPacks />);

    expect(await screen.findByRole("heading", { name: "Tabletop" })).toBeInTheDocument();
    expect(screen.getByText("Dice tower")).toBeInTheDocument();
    expect(screen.getByText("Natural 20")).toBeInTheDocument();
    expect(screen.getByText("d20")).toBeInTheDocument();
  });

  it("leaves out a pack that has not been downloaded", async () => {
    answerWith([
      entry("PACKTABTP00001", true),
      entry("PACKBAND000001", false, { name: "Soundcheck", slug: "music" }),
    ]);
    renderWithProviders(<MyDecorationPacks />);

    await screen.findByRole("heading", { name: "Tabletop" });
    expect(screen.queryByRole("heading", { name: "Soundcheck" })).not.toBeInTheDocument();
  });

  it("gives a pack back", async () => {
    answerWith([entry("PACKTABTP00001", true)]);
    renderWithProviders(<MyDecorationPacks />);

    await userEvent.click(await screen.findByRole("button", { name: "Give back" }));

    expect(removeMutate).toHaveBeenCalledWith("PACKTABTP00001");
  });

  it("points at the store when nothing has been downloaded", async () => {
    answerWith([entry("PACKTABTP00001", false)]);
    renderWithProviders(<MyDecorationPacks />);

    expect(await screen.findByText(/not downloaded a pack yet/)).toBeInTheDocument();
  });
});
