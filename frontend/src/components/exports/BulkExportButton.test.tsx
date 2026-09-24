import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { renderWithProviders } from "@/__tests__/helpers/render";
import { Tool } from "@/api/generated/initiativeAPI.schemas";

import { BulkExportButton } from "./BulkExportButton";

describe("BulkExportButton", () => {
  it("exports a selection its viewer owns every item of", () => {
    renderWithProviders(
      <BulkExportButton
        tool={Tool.queue}
        items={[
          { id: 1, my_permission_level: "owner" },
          { id: 2, my_permission_level: "owner" },
        ]}
      />
    );

    expect(screen.getByRole("button", { name: "Export" })).toBeEnabled();
  });

  it("says why when one of the selection is only theirs to edit", () => {
    renderWithProviders(
      <BulkExportButton
        tool={Tool.queue}
        items={[
          { id: 1, my_permission_level: "owner" },
          { id: 2, my_permission_level: "write" },
        ]}
      />
    );

    const button = screen.getByRole("button", {
      name: "Only whoever can delete all of these can export them.",
    });
    expect(button).toBeDisabled();
  });
});
