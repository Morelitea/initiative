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

const entry = (id: string, installed: boolean) => ({
  id,
  installed,
  contents: [
    { id: `${id}.dicetower`, kind: "banner", source: id },
    { id: `${id}.natural20`, kind: "frame", source: id },
    { id: `${id}.d20`, kind: "badge", source: id },
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
    answerWith([entry("ttrpg", true)]);
    renderWithProviders(<MyDecorationPacks />);

    expect(await screen.findByRole("heading", { name: "Tabletop" })).toBeInTheDocument();
    expect(screen.getByText("Dice tower")).toBeInTheDocument();
    expect(screen.getByText("Natural 20")).toBeInTheDocument();
    expect(screen.getByText("d20")).toBeInTheDocument();
  });

  it("leaves out a pack that has not been downloaded", async () => {
    answerWith([entry("ttrpg", true), entry("music", false)]);
    renderWithProviders(<MyDecorationPacks />);

    await screen.findByRole("heading", { name: "Tabletop" });
    expect(screen.queryByRole("heading", { name: "Soundcheck" })).not.toBeInTheDocument();
  });

  it("gives a pack back", async () => {
    answerWith([entry("ttrpg", true)]);
    renderWithProviders(<MyDecorationPacks />);

    await userEvent.click(await screen.findByRole("button", { name: "Give back" }));

    expect(removeMutate).toHaveBeenCalledWith("ttrpg");
  });

  it("points at the store when nothing has been downloaded", async () => {
    answerWith([entry("ttrpg", false)]);
    renderWithProviders(<MyDecorationPacks />);

    expect(await screen.findByText(/not downloaded a pack yet/)).toBeInTheDocument();
  });
});
