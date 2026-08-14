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
import type { GuildAppDetail } from "@/api/appConnections";

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

vi.mock("@/hooks/useGuildApps", () => ({
  useUpdateGuildApp: () => ({ mutateAsync }),
}));

let roster = [
  { id: 1, name: "Platform" },
  { id: 2, name: "Marketing" },
];

vi.mock("@/hooks/useInitiatives", () => ({
  useInitiatives: () => ({ data: roster, isLoading: false }),
}));

const app = (placement: Record<string, unknown>) =>
  ({ id: 7, name: "Automations", placement }) as unknown as GuildAppDetail;

beforeEach(() => {
  sent.length = 0;
  release = [];
  holdSaves = false;
  mutateAsync.mockClear();
  roster = [
    { id: 1, name: "Platform" },
    { id: 2, name: "Marketing" },
  ];
});

const tick = async (name: string) => (await screen.findByLabelText(name)).click();

describe("AppPlacementPanel", () => {
  it("sends the selection the admin built, one tick at a time", async () => {
    renderPage(() => <AppPlacementPanel app={app({ initiatives: [] })} />);

    await tick("Platform");
    await waitFor(() => expect(sent).toEqual([{ placement: { initiatives: [1] } }]));

    await tick("Marketing");
    await waitFor(() =>
      expect(sent).toEqual([
        { placement: { initiatives: [1] } },
        { placement: { initiatives: [1, 2] } },
      ])
    );
  });

  it("does not start a second save while the first is in flight", async () => {
    // Both boxes are ticked before either save answers. Concurrent requests
    // could be stored in either order; chained ones cannot.
    holdSaves = true;
    renderPage(() => <AppPlacementPanel app={app({ initiatives: [] })} />);

    await tick("Platform");
    await waitFor(() => expect(mutateAsync).toHaveBeenCalledTimes(1));
    await tick("Marketing");

    // Still one: the second is queued behind the first rather than racing it.
    expect(mutateAsync).toHaveBeenCalledTimes(1);

    release[0]?.();
    await waitFor(() => expect(mutateAsync).toHaveBeenCalledTimes(2));
    expect(sent[1]).toEqual({ placement: { initiatives: [1, 2] } });
  });

  it("drops an id whose initiative is gone rather than resubmitting it", async () => {
    // Initiative 9 was chosen once and has since been deleted: it is in the
    // stored placement and on no row of the roster.
    renderPage(() => <AppPlacementPanel app={app({ initiatives: [1, 9] })} />);

    await tick("Marketing");
    await waitFor(() => expect(sent).toEqual([{ placement: { initiatives: [1, 2] } }]));
  });

  it("places the app everywhere again in one choice", async () => {
    renderPage(() => <AppPlacementPanel app={app({ initiatives: [1] })} />);

    (await screen.findByLabelText("Every initiative")).click();
    await waitFor(() => expect(sent).toEqual([{ placement: {} }]));
  });
});
