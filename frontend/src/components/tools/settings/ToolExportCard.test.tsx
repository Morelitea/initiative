import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { renderWithProviders } from "@/__tests__/helpers/render";
import { Tool } from "@/api/generated/initiativeAPI.schemas";
import { ToolSettingsProvider } from "@/components/tools/settings/ToolSettingsContext";

import { ToolExportCard } from "./ToolExportCard";

const noopMutation = () => ({ mutate: vi.fn(), isPending: false });

const renderCard = (tool: Tool) =>
  renderWithProviders(
    <ToolSettingsProvider
      value={{
        tool,
        entity: {
          id: 3,
          name: "Barovia",
          initiative_id: 1,
          my_permission_level: "owner",
          tags: [],
          grants: [],
          comments_enabled: true,
          archived_at: null,
          can_unarchive: false,
        },
        canManage: true,
        isOwner: true,
        setGrants: noopMutation(),
        remove: noopMutation(),
      }}
    >
      <ToolExportCard />
    </ToolSettingsProvider>
  );

describe("ToolExportCard", () => {
  it("names the file on a button with only one thing to download", async () => {
    renderCard(Tool.gallery);

    expect(
      await screen.findByRole("button", { name: "Importable file with pictures (.zip)" })
    ).toBeInTheDocument();
  });

  it("says a wiki's every download is a zip", async () => {
    renderCard(Tool.wiki);

    await userEvent.click(await screen.findByRole("button", { name: "Export" }));

    for (const name of ["PDF (.zip)", "Markdown (.zip)", "Word (.zip)", "Importable file (.zip)"]) {
      expect(await screen.findByRole("menuitem", { name })).toBeInTheDocument();
    }
  });
});
