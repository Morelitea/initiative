import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse } from "msw";
import { describe, expect, it, vi } from "vitest";

import { buildTagSummary, resetFactories } from "@/__tests__/factories";
import { guildHttp } from "@/__tests__/helpers/guildHttp";
import { server } from "@/__tests__/helpers/msw-server";
import { renderPage } from "@/__tests__/helpers/render";
import { Tool } from "@/api/generated/initiativeAPI.schemas";
import {
  type ToolSettingsEntity,
  ToolSettingsProvider,
} from "@/components/tools/settings/ToolSettingsContext";

import { ToolSettingsAccessPage } from "./ToolSettingsAccessPage";
import { ToolSettingsAdvancedPage } from "./ToolSettingsAdvancedPage";
import { ToolSettingsDetailsPage } from "./ToolSettingsDetailsPage";

const ADDED_TAG = buildTagSummary({ id: 99, name: "Added tag" });

// The picker's own UI is not what these tests are about — this stub reports the
// selection it was handed and offers one way to change it.
vi.mock("@/components/tags", () => ({
  TagPicker: ({
    selectedTags,
    onChange,
  }: {
    selectedTags: { id: number; name: string }[];
    onChange: (tags: { id: number; name: string }[]) => void;
  }) => (
    <div>
      <span data-testid="selected-tags">{selectedTags.map((tag) => tag.name).join(",")}</span>
      <button type="button" onClick={() => onChange([ADDED_TAG])}>
        pick tag
      </button>
    </div>
  ),
}));

const buildEntity = (overrides: Partial<ToolSettingsEntity> = {}): ToolSettingsEntity => ({
  id: 7,
  name: "Q3 Roadmap",
  description: "A description",
  initiative_id: 3,
  my_permission_level: "owner",
  tags: [],
  grants: [],
  comments_enabled: true,
  ...overrides,
});

const noopMutation = () => ({ mutate: vi.fn(), isPending: false });

/** One section, mounted the way its route mounts it: inside the frame's context. */
const renderSection = (Section: React.ComponentType, entity: ToolSettingsEntity) =>
  renderPage(() => (
    <ToolSettingsProvider
      value={{
        tool: Tool.queue,
        entity,
        canManage: entity.my_permission_level !== "read",
        isOwner: entity.my_permission_level === "owner",
        setGrants: noopMutation(),
        remove: noopMutation(),
      }}
    >
      <Section />
    </ToolSettingsProvider>
  ));

describe("ToolSettingsDetailsPage tags", () => {
  it("keeps the new selection when the write succeeds", async () => {
    resetFactories();
    server.use(guildHttp.put("/tools/:tool/:toolId/tags", () => HttpResponse.json([ADDED_TAG])));
    renderSection(ToolSettingsDetailsPage, buildEntity());

    await userEvent.click(await screen.findByRole("button", { name: "pick tag" }));

    await waitFor(() => expect(screen.getByTestId("selected-tags")).toHaveTextContent("Added tag"));
  });

  it("puts the previous selection back when the write fails", async () => {
    resetFactories();
    const existing = buildTagSummary({ id: 1, name: "Existing tag" });
    server.use(
      guildHttp.put("/tools/:tool/:toolId/tags", () =>
        HttpResponse.json({ detail: "NOPE" }, { status: 500 })
      )
    );
    renderSection(ToolSettingsDetailsPage, buildEntity({ tags: [existing] }));

    expect(await screen.findByTestId("selected-tags")).toHaveTextContent("Existing tag");

    await userEvent.click(screen.getByRole("button", { name: "pick tag" }));

    // Shown optimistically, then rolled back — the picker must never keep a
    // selection the server rejected.
    await waitFor(() =>
      expect(screen.getByTestId("selected-tags")).toHaveTextContent("Existing tag")
    );
    expect(screen.getByTestId("selected-tags")).not.toHaveTextContent("Added tag");
  });
});

describe("ToolSettingsDetailsPage comments switch", () => {
  it("turns comments off and keeps the new state", async () => {
    resetFactories();
    server.use(
      guildHttp.put("/tools/:tool/:toolId/comments", () =>
        HttpResponse.json({ comments_enabled: false })
      )
    );
    renderSection(ToolSettingsDetailsPage, buildEntity());

    // Stated the way it is labelled: on means comments happen.
    const toggle = await screen.findByRole("switch", { name: "Enable comments" });
    expect(toggle).toBeChecked();

    await userEvent.click(toggle);

    await waitFor(() => expect(toggle).not.toBeChecked());
  });

  it("puts the switch back when the write fails", async () => {
    resetFactories();
    server.use(
      guildHttp.put("/tools/:tool/:toolId/comments", () =>
        HttpResponse.json({ detail: "NOPE" }, { status: 500 })
      )
    );
    renderSection(ToolSettingsDetailsPage, buildEntity());

    const toggle = await screen.findByRole("switch", { name: "Enable comments" });
    await userEvent.click(toggle);

    await waitFor(() => expect(toggle).toBeChecked());
  });
});

describe("ToolSettingsAdvancedPage", () => {
  it("offers deletion to the owner", async () => {
    resetFactories();
    renderSection(ToolSettingsAdvancedPage, buildEntity());

    expect(await screen.findByRole("button", { name: "Delete" })).toBeInTheDocument();
  });

  it("says so rather than rendering a blank page when it holds nothing", async () => {
    resetFactories();
    // Deletion is the owner's alone and this tool declares no extras, so the
    // tab bar hides the link — but the address is still typeable.
    renderSection(ToolSettingsAdvancedPage, buildEntity({ my_permission_level: "read" }));

    expect(await screen.findByText("Permission required")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Delete" })).not.toBeInTheDocument();
  });
});

describe("ToolSettingsAccessPage", () => {
  it("refuses a reader who reached the address without write access", async () => {
    resetFactories();
    // The tab bar hides this section from them; the address is still typeable,
    // so the section says no on its own.
    renderSection(ToolSettingsAccessPage, buildEntity({ my_permission_level: "read" }));

    expect(await screen.findByText("Permission required")).toBeInTheDocument();
  });
});
