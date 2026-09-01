import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { renderPage } from "@/__tests__/helpers/render";
import { Tool } from "@/api/generated/initiativeAPI.schemas";

import { type ToolSettingsEntity, ToolSettingsLayout } from "./ToolSettingsLayout";

const buildEntity = (overrides: Partial<ToolSettingsEntity> = {}): ToolSettingsEntity => ({
  id: 7,
  name: "Q3 Roadmap",
  description: "A description",
  initiative_id: 3,
  my_permission_level: "owner",
  tags: [],
  grants: [],
  ...overrides,
});

const noopMutation = () => ({ mutate: vi.fn(), isPending: false });

/** The settings frame at one of its section addresses. */
const renderLayout = ({
  entity = buildEntity(),
  path = "",
  extraTabs,
}: {
  entity?: ToolSettingsEntity;
  path?: string;
  extraTabs?: { value: string; label: string }[];
} = {}) =>
  renderPage(
    () => (
      <ToolSettingsLayout
        tool={Tool.queue}
        entity={entity}
        isLoading={false}
        isError={false}
        setGrants={noopMutation()}
        remove={noopMutation()}
        extraTabs={extraTabs}
      />
    ),
    {
      initialRoute: `/c/$guildId/i/$initiativeId/queues/$queueId/settings${path}`,
      routeParams: { guildId: "1", initiativeId: "3", queueId: "7" },
    }
  );

describe("ToolSettingsLayout", () => {
  it("names every section as a tab", async () => {
    renderLayout();

    for (const label of ["Details", "Access", "Advanced"]) {
      expect(await screen.findByRole("tab", { name: label })).toBeInTheDocument();
    }
  });

  it("navigates to the section a tab names", async () => {
    const { router } = renderLayout();

    await userEvent.click(await screen.findByRole("tab", { name: "Access" }));

    // The section is an address, not a piece of component state.
    expect(router.state.location.pathname).toBe("/c/1/i/3/queues/7/settings/access");
  });

  it("lights the tab the address names", async () => {
    renderLayout({ path: "/advanced" });

    expect(await screen.findByRole("tab", { name: "Advanced" })).toHaveAttribute(
      "aria-selected",
      "true"
    );
  });

  it("opens on Details, which is the settings address itself", async () => {
    renderLayout();

    expect(await screen.findByRole("tab", { name: "Details" })).toHaveAttribute(
      "aria-selected",
      "true"
    );
  });

  it("keeps the access tab out of the bar for a reader who may not share", async () => {
    renderLayout({ entity: buildEntity({ my_permission_level: "read" }) });

    expect(await screen.findByRole("tab", { name: "Details" })).toBeInTheDocument();
    expect(screen.queryByRole("tab", { name: "Access" })).not.toBeInTheDocument();
  });

  it("gives a tool's own section a route beside the shared ones", async () => {
    const { router } = renderLayout({
      extraTabs: [{ value: "task-statuses", label: "Task statuses" }],
    });

    await userEvent.click(await screen.findByRole("tab", { name: "Task statuses" }));

    expect(router.state.location.pathname).toBe("/c/1/i/3/queues/7/settings/task-statuses");
  });

  it("addresses a guild-level entity at its guild route", async () => {
    renderPage(
      () => (
        <ToolSettingsLayout
          tool={Tool.calendar}
          entity={buildEntity({ initiative_id: null })}
          isLoading={false}
          isError={false}
          setGrants={noopMutation()}
          remove={noopMutation()}
        />
      ),
      {
        initialRoute: "/c/$guildId/calendars/$calendarId/settings",
        routeParams: { guildId: "1", calendarId: "7" },
      }
    );

    expect(await screen.findByRole("tab", { name: "Details" })).toHaveAttribute(
      "aria-selected",
      "true"
    );
  });
});
