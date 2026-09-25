/**
 * What reaches the server when an admin picks initiatives.
 *
 * Each save replaces the whole selection, which makes two things matter that a
 * single-field form never has to think about.
 *
 * **Order.** Ticking two boxes quickly starts two saves. If they were sent
 * concurrently the slower one could land last and store the older selection, so
 * they are chained and the server sees them in the order they were made.
 *
 * **What is still there.** An initiative deleted after it was chosen leaves an
 * id behind that nothing on screen shows. Resubmitting it would be refused, and
 * the admin would have no way to see why — so the selection sent is the one
 * being displayed.
 */

import { screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { renderPage } from "@/__tests__/helpers/render";
import type { GuildAppDetail } from "@/api/generated/initiativeAPI.schemas";

import { AppPlacementPanel } from "./AppPlacementPanel";

/** Every payload handed to the update mutation, in the order it was sent. */
const sent: unknown[] = [];
/** Resolves the in-flight save, so a test can hold one open. */
let release: Array<() => void> = [];
let holdSaves = false;

const mutateAsync = vi.fn((body: unknown) => {
  sent.push(body);
  if (!holdSaves) return Promise.resolve({});
  return new Promise<object>((resolve) => release.push(() => resolve({})));
});

/** Every role save, as the hook was called with it. */
const roleSaves: unknown[] = [];
const setRoles = vi.fn(
  (
    variables: { initiativeId: number; roleIds: number[] },
    handlers?: { onSuccess?: (placement: { role_ids: number[] }) => void }
  ) => {
    roleSaves.push(variables);
    handlers?.onSuccess?.({ role_ids: variables.roleIds });
  }
);

vi.mock("@/hooks/useGuildApps", () => ({
  useUpdateGuildApp: () => ({ mutateAsync }),
  useSetAppPlacementRoles: () => ({ mutate: setRoles, isPending: false }),
}));

/** The initiatives whose roles were asked for. */
const rolesAskedFor: Array<number | null> = [];

vi.mock("@/hooks/useInitiativeRoles", () => ({
  useInitiativeRoles: (initiativeId: number | null) => {
    rolesAskedFor.push(initiativeId);
    return {
      isLoading: false,
      data: [
        { id: 11, display_name: "Project manager" },
        { id: 12, display_name: "Member" },
      ],
    };
  },
}));

let roster = [
  { id: 1, name: "Platform" },
  { id: 2, name: "Marketing" },
];

vi.mock("@/hooks/useInitiatives", () => ({
  useInitiatives: () => ({ data: roster, isLoading: false }),
}));

/** A page the app shows inside initiatives. */
const initiativePage = { id: "board", path: "/board", scopes: ["initiative"] };

/**
 * An install placed in these initiatives, each allowing ``roleIds``. It shows
 * a page inside initiatives unless ``page`` is false.
 */
const app = (placed: number[], roleIds: number[] = [], page = true) =>
  ({
    id: 7,
    name: "Automations",
    definition: { embeds: page ? [initiativePage] : [] },
    requested_scopes: ["projects:read"],
    placements: placed.map((initiative_id) => ({ initiative_id, role_ids: roleIds })),
  }) as unknown as GuildAppDetail;

beforeEach(() => {
  sent.length = 0;
  release = [];
  holdSaves = false;
  mutateAsync.mockClear();
  roleSaves.length = 0;
  setRoles.mockClear();
  rolesAskedFor.length = 0;
  roster = [
    { id: 1, name: "Platform" },
    { id: 2, name: "Marketing" },
  ];
});

const tick = async (name: string) => (await screen.findByLabelText(name)).click();

describe("AppPlacementPanel", () => {
  it("sends the selection the admin built, one tick at a time", async () => {
    renderPage(() => <AppPlacementPanel app={app([])} />);

    await tick("Platform");
    await waitFor(() => expect(sent).toEqual([{ placed_initiative_ids: [1] }]));

    await tick("Marketing");
    await waitFor(() =>
      expect(sent).toEqual([{ placed_initiative_ids: [1] }, { placed_initiative_ids: [1, 2] }])
    );
  });

  it("does not start a second save while the first is in flight", async () => {
    // Both boxes are ticked before either save answers. Concurrent requests
    // could be stored in either order; chained ones cannot.
    holdSaves = true;
    renderPage(() => <AppPlacementPanel app={app([])} />);

    await tick("Platform");
    await waitFor(() => expect(mutateAsync).toHaveBeenCalledTimes(1));
    await tick("Marketing");

    // Still one: the second is queued behind the first rather than racing it.
    expect(mutateAsync).toHaveBeenCalledTimes(1);

    release[0]?.();
    await waitFor(() => expect(mutateAsync).toHaveBeenCalledTimes(2));
    expect(sent[1]).toEqual({ placed_initiative_ids: [1, 2] });
  });

  it("drops an id whose initiative is gone rather than resubmitting it", async () => {
    // Initiative 9 was chosen once and has since been deleted: it is in the
    // stored placement and on no row of the roster.
    renderPage(() => <AppPlacementPanel app={app([1, 9])} />);

    await tick("Marketing");
    await waitFor(() => expect(sent).toEqual([{ placed_initiative_ids: [1, 2] }]));
  });

  it("leaves the next edit building on what the server kept", async () => {
    // The first save fails while a second is already queued behind it. The
    // second succeeds, so the server holds that selection — and the panel has
    // to agree, or the following edit is computed from a state nobody stored.
    let rejectFirst: (reason: unknown) => void = () => {};
    mutateAsync.mockImplementationOnce((body: unknown) => {
      sent.push(body);
      return new Promise<object>((_resolve, reject) => {
        rejectFirst = reject;
      });
    });
    renderPage(() => <AppPlacementPanel app={app([])} />);

    await tick("Platform");
    await waitFor(() => expect(mutateAsync).toHaveBeenCalledTimes(1));
    await tick("Marketing");

    rejectFirst(new Error("refused"));
    await waitFor(() => expect(sent[1]).toEqual({ placed_initiative_ids: [1, 2] }));

    // Untick the first one. Built on [1, 2] — what the server took — rather
    // than on the empty selection the failed save would have rolled back to.
    await tick("Platform");
    await waitFor(() => expect(sent[2]).toEqual({ placed_initiative_ids: [2] }));
  });

  it("places the app in every current initiative in one choice", async () => {
    renderPage(() => <AppPlacementPanel app={app([1])} />);

    (await screen.findByLabelText("Every current initiative")).click();
    await waitFor(() => expect(sent).toEqual([{ placed_initiative_ids: [1, 2] }]));
  });

  it("reads an app placed in every initiative as every current one", async () => {
    renderPage(() => <AppPlacementPanel app={app([1, 2])} />);

    expect(await screen.findByLabelText("Every current initiative")).toBeChecked();
    expect(screen.queryByLabelText("Platform")).toBeNull();
  });

  it("choosing to pick shows the current placements and saves nothing", async () => {
    renderPage(() => <AppPlacementPanel app={app([1, 2])} />);

    (await screen.findByLabelText("Only the initiatives I choose")).click();
    expect(await screen.findByLabelText("Platform")).toBeChecked();
    expect(screen.getByLabelText("Marketing")).toBeChecked();
    expect(sent).toEqual([]);
  });

  describe("who can open it", () => {
    it("loads an initiative's roles only when its chooser opens", async () => {
      renderPage(() => <AppPlacementPanel app={app([1])} />);

      const trigger = await screen.findByLabelText("Who can open it in Platform");
      expect(trigger).toHaveTextContent("Community admins only");
      // Marketing is not placed, so it has no chooser at all.
      expect(screen.queryByLabelText("Who can open it in Marketing")).toBeNull();
      expect(rolesAskedFor.filter((id) => id !== null)).toEqual([]);

      trigger.click();
      expect(await screen.findByText("Community admins can always open it.")).toBeTruthy();
      expect(new Set(rolesAskedFor)).toEqual(new Set([1]));
    });

    it("saves the whole role set for that one initiative", async () => {
      renderPage(() => <AppPlacementPanel app={app([1], [11])} />);

      const trigger = await screen.findByLabelText("Who can open it in Platform");
      expect(trigger).toHaveTextContent("1 role");
      trigger.click();

      expect(await screen.findByLabelText("Project manager")).toBeChecked();
      (await screen.findByLabelText("Member")).click();
      await waitFor(() => expect(roleSaves).toEqual([{ initiativeId: 1, roleIds: [11, 12] }]));
      expect(screen.getByLabelText("Member")).toBeChecked();

      screen.getByLabelText("Project manager").click();
      await waitFor(() => expect(roleSaves[1]).toEqual({ initiativeId: 1, roleIds: [12] }));
      // Roles never go through the whole-selection save.
      expect(sent).toEqual([]);
    });

    it("offers the roles of each placement when placed everywhere", async () => {
      renderPage(() => <AppPlacementPanel app={app([1, 2], [11, 12])} />);

      expect(await screen.findByLabelText("Who can open it in Platform")).toHaveTextContent(
        "2 roles"
      );
      expect(screen.getByLabelText("Who can open it in Marketing")).toBeTruthy();
    });

    it("offers no roles for an app with no page inside initiatives", async () => {
      renderPage(() => <AppPlacementPanel app={app([1, 2], [11], false)} />);

      expect(
        await screen.findByText(
          "This app reads and changes things only in the initiatives you choose."
        )
      ).toBeTruthy();
      expect(screen.queryByLabelText("Who can open it in Platform")).toBeNull();
    });
  });
});
