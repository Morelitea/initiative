import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse } from "msw";
import { describe, expect, it, vi } from "vitest";

import { buildTagSummary, resetFactories } from "@/__tests__/factories";
import { guildHttp } from "@/__tests__/helpers/guildHttp";
import { server } from "@/__tests__/helpers/msw-server";
import { renderPage } from "@/__tests__/helpers/render";
import { Tool } from "@/api/generated/initiativeAPI.schemas";

import { type ToolSettingsEntity, ToolSettingsPage } from "./ToolSettingsPage";

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
  comments_disabled: false,
  ...overrides,
});

const noopMutation = () => ({ mutate: vi.fn(), isPending: false });

// The breadcrumb renders router Links, so this needs a real router around it.
const renderSettings = (entity: ToolSettingsEntity) =>
  renderPage(() => (
    <ToolSettingsPage
      tool={Tool.queue}
      entity={entity}
      isLoading={false}
      isError={false}
      setGrants={noopMutation()}
      remove={noopMutation()}
    />
  ));

describe("ToolSettingsPage tags", () => {
  it("keeps the new selection when the write succeeds", async () => {
    resetFactories();
    server.use(guildHttp.put("/tools/:tool/:toolId/tags", () => HttpResponse.json([ADDED_TAG])));
    renderSettings(buildEntity());

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
    renderSettings(buildEntity({ tags: [existing] }));

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

describe("ToolSettingsPage comments switch", () => {
  const openAdvanced = async () =>
    userEvent.click(await screen.findByRole("tab", { name: "Advanced" }));

  it("turns comments off and keeps the new state", async () => {
    resetFactories();
    server.use(
      guildHttp.put("/tools/:tool/:toolId/comments", () =>
        HttpResponse.json({ comments_disabled: true })
      )
    );
    renderSettings(buildEntity());
    await openAdvanced();

    const toggle = await screen.findByRole("switch", { name: "Disable comments" });
    expect(toggle).not.toBeChecked();

    await userEvent.click(toggle);

    await waitFor(() => expect(toggle).toBeChecked());
  });

  it("puts the switch back when the write fails", async () => {
    resetFactories();
    server.use(
      guildHttp.put("/tools/:tool/:toolId/comments", () =>
        HttpResponse.json({ detail: "NOPE" }, { status: 500 })
      )
    );
    renderSettings(buildEntity());
    await openAdvanced();

    const toggle = await screen.findByRole("switch", { name: "Disable comments" });
    await userEvent.click(toggle);

    await waitFor(() => expect(toggle).not.toBeChecked());
  });
});
