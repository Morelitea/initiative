/**
 * The two things this panel decides: what the switch sends, and whether there
 * is an update to offer at all.
 *
 * Both are easy to get backwards. The switch reflects an install that is
 * already tracking, so an admin's first interaction with it is turning it
 * *off* — a panel that sent `auto_update: true` there would silently confirm
 * the state it was meant to leave. And the Update button is drawn from the
 * server's `update_version` rather than from a comparison invented here, so an
 * install on the newest version must not offer one.
 */

import { screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { renderPage } from "@/__tests__/helpers/render";
import type { GuildAppDetail } from "@/api/generated/initiativeAPI.schemas";

import { AppUpdatesPanel } from "./AppUpdatesPanel";

const patched: unknown[] = [];
const upgraded = vi.fn();

vi.mock("@/hooks/useGuildApps", () => ({
  useUpdateGuildApp: () => ({
    isPending: false,
    mutate: (body: unknown) => patched.push(body),
  }),
}));

const declined = vi.fn();

vi.mock("@/hooks/useGuildAppDetail", () => ({
  useUpgradeApp: () => ({ isPending: false, mutate: upgraded }),
  useDeclineAppUpgrade: () => ({ isPending: false, mutate: declined }),
}));

const app = (overrides: Partial<GuildAppDetail>) =>
  ({
    id: 7,
    name: "Community calendar",
    listing_version: "1.0.0",
    auto_update: true,
    ...overrides,
  }) as unknown as GuildAppDetail;

beforeEach(() => {
  patched.length = 0;
  upgraded.mockClear();
  declined.mockClear();
});

describe("AppUpdatesPanel", () => {
  it("shows an install as tracking, and turns that off when asked", async () => {
    renderPage(() => <AppUpdatesPanel app={app({})} />);

    const toggle = await screen.findByLabelText("Update automatically");
    expect(toggle).toBeChecked();

    toggle.click();
    expect(patched).toEqual([{ auto_update: false }]);
  });

  it("turns tracking back on from the manual state", async () => {
    renderPage(() => <AppUpdatesPanel app={app({ auto_update: false })} />);

    const toggle = await screen.findByLabelText("Update automatically");
    expect(toggle).not.toBeChecked();

    toggle.click();
    expect(patched).toEqual([{ auto_update: true }]);
  });

  it("offers the version the server named, and applies it", async () => {
    renderPage(() => <AppUpdatesPanel app={app({ update_version: "1.2.0" })} />);

    const button = await screen.findByRole("button", { name: "Update to 1.2.0" });
    button.click();
    expect(upgraded).toHaveBeenCalledOnce();
  });

  it("offers nothing when the server named no version", async () => {
    renderPage(() => <AppUpdatesPanel app={app({ update_version: null })} />);

    expect(await screen.findByText("Up to date")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Update to/ })).not.toBeInTheDocument();
  });

  it("says what a version asking for more wants, and accepts it with its scopes", async () => {
    renderPage(() => (
      <AppUpdatesPanel
        app={app({
          update_version: "1.2.0",
          pending_update: {
            version: "1.2.0",
            added_scopes: ["documents:write"],
            added_surfaces: [{ id: "planner", name: { en: "Planner" } }],
            declined: false,
          },
        })}
      />
    ));

    expect(await screen.findByText("Version 1.2.0 wants to:")).toBeInTheDocument();
    expect(screen.getByText("Read and change documents")).toBeInTheDocument();
    expect(screen.getByText("Show “Planner” inside initiatives")).toBeInTheDocument();
    // The plain Update button is not offered beside the question.
    expect(screen.queryByRole("button", { name: /Update to/ })).not.toBeInTheDocument();

    screen.getByRole("button", { name: "Accept and update" }).click();
    expect(upgraded).toHaveBeenCalledWith(
      { version: "1.2.0", add_scopes: ["documents:write"] },
      expect.anything()
    );
  });

  it("says a version asking to use another app names that app", async () => {
    renderPage(() => (
      <AppUpdatesPanel
        app={app({
          update_version: "1.3.0",
          app_names: { "acme.github": "GitHub" },
          pending_update: {
            version: "1.3.0",
            added_scopes: ["apps:acme.github"],
            added_surfaces: [],
            declined: false,
          },
        })}
      />
    ));

    expect(await screen.findByText("Use GitHub in this community")).toBeInTheDocument();
  });

  it("declines the version it was shown", async () => {
    renderPage(() => (
      <AppUpdatesPanel
        app={app({
          update_version: "1.2.0",
          pending_update: {
            version: "1.2.0",
            added_scopes: ["documents:read"],
            added_surfaces: [],
            declined: false,
          },
        })}
      />
    ));

    (await screen.findByRole("button", { name: "Decline" })).click();
    expect(declined).toHaveBeenCalledWith("1.2.0", expect.anything());
  });

  it("says a declined version was declined, and offers only to accept it", async () => {
    renderPage(() => (
      <AppUpdatesPanel
        app={app({
          update_version: "1.2.0",
          pending_update: {
            version: "1.2.0",
            added_scopes: ["documents:read"],
            added_surfaces: [],
            declined: true,
          },
        })}
      />
    ));

    expect(
      await screen.findByText("You declined version 1.2.0. The app stays on its current version.")
    ).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Decline" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Accept and update" })).toBeInTheDocument();
  });
});
