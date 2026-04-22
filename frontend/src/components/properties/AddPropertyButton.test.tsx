import { describe, expect, it, vi } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";

import { renderWithProviders } from "@/__tests__/helpers/render";
import { server } from "@/__tests__/helpers/msw-server";
import { buildPropertyDefinition } from "@/__tests__/factories/properties";
import {
  PropertyAppliesTo,
  PropertyType,
  type PropertyDefinitionRead,
} from "@/api/generated/initiativeAPI.schemas";

import { AddPropertyButton } from "./AddPropertyButton";

const mockDefinitions = (defs: PropertyDefinitionRead[]) => {
  server.use(http.get("/api/v1/property-definitions/", () => HttpResponse.json(defs)));
};

describe("AddPropertyButton", () => {
  it("lists only definitions whose applies_to is compatible with the entity kind", async () => {
    mockDefinitions([
      buildPropertyDefinition({
        id: 1,
        name: "Doc Only",
        applies_to: PropertyAppliesTo.document,
      }),
      buildPropertyDefinition({
        id: 2,
        name: "Task Only",
        applies_to: PropertyAppliesTo.task,
      }),
      buildPropertyDefinition({
        id: 3,
        name: "Both",
        applies_to: PropertyAppliesTo.both,
      }),
    ]);
    renderWithProviders(
      <AddPropertyButton entityKind="document" currentPropertyIds={[]} onAdd={vi.fn()} />
    );
    await userEvent.click(screen.getByRole("button", { name: /Add property/i }));
    await waitFor(() => expect(screen.getByText("Doc Only")).toBeInTheDocument());
    expect(screen.getByText("Both")).toBeInTheDocument();
    expect(screen.queryByText("Task Only")).not.toBeInTheDocument();
  });

  it("filters out definitions whose id is in currentPropertyIds", async () => {
    mockDefinitions([
      buildPropertyDefinition({
        id: 1,
        name: "Alpha",
        applies_to: PropertyAppliesTo.both,
      }),
      buildPropertyDefinition({
        id: 2,
        name: "Beta",
        applies_to: PropertyAppliesTo.both,
      }),
    ]);
    renderWithProviders(
      <AddPropertyButton entityKind="document" currentPropertyIds={[1]} onAdd={vi.fn()} />
    );
    await userEvent.click(screen.getByRole("button", { name: /Add property/i }));
    await waitFor(() => expect(screen.getByText("Beta")).toBeInTheDocument());
    expect(screen.queryByText("Alpha")).not.toBeInTheDocument();
  });

  it("calls onAdd(definition) when an existing definition is picked", async () => {
    const defs = [
      buildPropertyDefinition({
        id: 7,
        name: "Priority",
        applies_to: PropertyAppliesTo.both,
      }),
    ];
    mockDefinitions(defs);
    const onAdd = vi.fn();
    renderWithProviders(
      <AddPropertyButton entityKind="document" currentPropertyIds={[]} onAdd={onAdd} />
    );
    await userEvent.click(screen.getByRole("button", { name: /Add property/i }));
    const item = await screen.findByText("Priority");
    await userEvent.click(item);
    expect(onAdd).toHaveBeenCalledTimes(1);
    expect(onAdd).toHaveBeenCalledWith(expect.objectContaining({ id: 7, name: "Priority" }));
  });

  it("filters the list case-insensitively by the search input", async () => {
    mockDefinitions([
      buildPropertyDefinition({
        id: 1,
        name: "Alpha",
        applies_to: PropertyAppliesTo.both,
      }),
      buildPropertyDefinition({
        id: 2,
        name: "Beta",
        applies_to: PropertyAppliesTo.both,
      }),
    ]);
    renderWithProviders(
      <AddPropertyButton entityKind="document" currentPropertyIds={[]} onAdd={vi.fn()} />
    );
    await userEvent.click(screen.getByRole("button", { name: /Add property/i }));
    const searchInput = await screen.findByPlaceholderText(/Search properties/i);
    await userEvent.type(searchInput, "BET");
    await waitFor(() => {
      expect(screen.getByText("Beta")).toBeInTheDocument();
      expect(screen.queryByText("Alpha")).not.toBeInTheDocument();
    });
  });

  it("creates a new property via the mutation and calls onAdd with the returned definition", async () => {
    mockDefinitions([]);

    const bodies: unknown[] = [];
    server.use(
      http.post("/api/v1/property-definitions/", async ({ request }) => {
        const body = await request.json();
        bodies.push(body);
        return HttpResponse.json(
          buildPropertyDefinition({
            id: 99,
            name: (body as { name: string }).name,
            type: (body as { type: PropertyType }).type,
            applies_to: PropertyAppliesTo.document,
          })
        );
      })
    );

    const onAdd = vi.fn();
    renderWithProviders(
      <AddPropertyButton entityKind="document" currentPropertyIds={[]} onAdd={onAdd} />
    );

    await userEvent.click(screen.getByRole("button", { name: /Add property/i }));
    // "Create new property" entry in the command list.
    const createEntry = await screen.findByText(/Create new property/i);
    await userEvent.click(createEntry);

    // Fill in the name.
    const nameInput = await screen.findByLabelText(/Property name/i);
    await userEvent.type(nameInput, "Quarter");
    // Default type is text, so submit directly.
    const submit = screen.getByRole("button", { name: "Create" });
    await userEvent.click(submit);

    await waitFor(() => {
      expect(bodies).toHaveLength(1);
    });
    expect(bodies[0]).toEqual(
      expect.objectContaining({
        name: "Quarter",
        type: "text",
        applies_to: "both",
      })
    );
    await waitFor(() =>
      expect(onAdd).toHaveBeenCalledWith(expect.objectContaining({ id: 99, name: "Quarter" }))
    );
  });

  it("disables the trigger when disabled=true", () => {
    mockDefinitions([]);
    renderWithProviders(
      <AddPropertyButton entityKind="document" currentPropertyIds={[]} onAdd={vi.fn()} disabled />
    );
    expect(screen.getByRole("button", { name: /Add property/i })).toBeDisabled();
  });
});
