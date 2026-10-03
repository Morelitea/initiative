import { act, fireEvent, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse } from "msw";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  buildPropertyDefinition,
  buildPropertyOption,
  buildPropertySummary,
} from "@/__tests__/factories/properties";
import { communityHttp } from "@/__tests__/helpers/communityHttp";
import { server } from "@/__tests__/helpers/msw-server";
import { renderWithProviders } from "@/__tests__/helpers/render";
import {
  type PropertySummary,
  PropertyTarget,
  PropertyType,
} from "@/api/generated/initiativeAPI.schemas";

import { PropertyPanel } from "./PropertyPanel";

describe("PropertyPanel", () => {
  beforeEach(() => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  const advanceDebounce = async () => {
    await act(async () => {
      vi.advanceTimersByTime(500);
    });
  };

  it("renders one row per property", () => {
    const properties: PropertySummary[] = [
      buildPropertySummary({ property_id: 1, name: "Status", type: PropertyType.text }),
      buildPropertySummary({ property_id: 2, name: "Owner", type: PropertyType.text }),
    ];
    renderWithProviders(
      <PropertyPanel
        target={PropertyTarget.document}
        entityId={10}
        initiativeId={1}
        saved={properties}
      />
    );
    expect(screen.getByText("Status")).toBeInTheDocument();
    expect(screen.getByText("Owner")).toBeInTheDocument();
  });

  it("attaches an added property without writing over a value just entered", async () => {
    const bodies: unknown[] = [];
    server.use(
      communityHttp.get("/property-definitions/", () =>
        HttpResponse.json([buildPropertyDefinition({ id: 2, name: "Owner" })])
      ),
      communityHttp.put("/properties/:target/:entityId", async ({ request }) => {
        bodies.push(await request.json());
        return HttpResponse.json([]);
      })
    );
    const status = buildPropertySummary({
      property_id: 1,
      name: "Status",
      type: PropertyType.text,
      value: null,
    });
    renderWithProviders(
      <PropertyPanel
        target={PropertyTarget.calendar_event}
        entityId={9}
        initiativeId={1}
        saved={[status]}
      />
    );
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });

    // Filled in, then another added before the row comes back from the server.
    fireEvent.change(screen.getByPlaceholderText("Empty"), { target: { value: "Ready" } });
    await user.click(screen.getByRole("button", { name: /Add property/i }));
    await user.click(await screen.findByText("Owner"));
    await advanceDebounce();

    expect(bodies.at(-1)).toEqual({
      values: [
        { property_id: 1, value: "Ready" },
        { property_id: 2, value: null },
      ],
    });
    expect(bodies).not.toContainEqual({
      values: expect.arrayContaining([{ property_id: 1, value: null }]),
    });
  });

  it("writes the values through the one route after the debounce when a value changes", async () => {
    const requests: Array<{ url: string; body: unknown }> = [];
    server.use(
      communityHttp.put("/properties/:target/:entityId", async ({ request, params }) => {
        requests.push({
          url: `/api/v1/properties/${params.target}/${params.entityId}`,
          body: await request.json(),
        });
        return HttpResponse.json([]);
      })
    );

    const props: PropertySummary[] = [
      buildPropertySummary({
        property_id: 42,
        name: "Owner",
        type: PropertyType.text,
        value: "",
      }),
    ];
    renderWithProviders(
      <PropertyPanel target={PropertyTarget.document} entityId={7} initiativeId={1} saved={props} />
    );

    const input = screen.getByPlaceholderText("Empty") as HTMLInputElement;
    fireEvent.change(input, { target: { value: "Ada" } });

    // Before the debounce fires we should have no network calls yet.
    expect(requests).toHaveLength(0);
    await advanceDebounce();

    // One PUT with the changed value.
    expect(requests).toHaveLength(1);
    expect(requests[0].url).toBe("/api/v1/properties/document/7");
    expect(requests[0].body).toEqual({ values: [{ property_id: 42, value: "Ada" }] });
  });

  it("sends an untouched user_reference property back as the user's id", async () => {
    const requests: Array<{ body: unknown }> = [];
    server.use(
      communityHttp.put("/properties/:target/:entityId", async ({ request }) => {
        requests.push({ body: await request.json() });
        return HttpResponse.json([]);
      })
    );

    const props: PropertySummary[] = [
      buildPropertySummary({
        property_id: 1,
        name: "Reviewer",
        type: PropertyType.user_reference,
        value: { id: 7, display_name: "Grace" },
      }),
      buildPropertySummary({ property_id: 2, name: "Owner", type: PropertyType.text, value: "" }),
    ];
    renderWithProviders(
      <PropertyPanel target={PropertyTarget.document} entityId={1} initiativeId={1} saved={props} />
    );

    expect(screen.getByText("Grace")).toBeInTheDocument();
    fireEvent.change(screen.getByPlaceholderText("Empty"), { target: { value: "Ada" } });
    await advanceDebounce();

    expect(requests[0].body).toEqual({
      values: [
        { property_id: 1, value: 7 },
        { property_id: 2, value: "Ada" },
      ],
    });
  });

  it("addresses a task by its target, not by the task's own update", async () => {
    const requests: Array<{ url: string; body: unknown }> = [];
    server.use(
      communityHttp.put("/properties/:target/:entityId", async ({ request, params }) => {
        requests.push({
          url: `/api/v1/properties/${params.target}/${params.entityId}`,
          body: await request.json(),
        });
        return HttpResponse.json([]);
      })
    );

    const props: PropertySummary[] = [
      buildPropertySummary({ property_id: 5, name: "Hours", type: PropertyType.number, value: 1 }),
    ];
    renderWithProviders(
      <PropertyPanel target={PropertyTarget.task} entityId={99} initiativeId={1} saved={props} />
    );

    const input = screen.getByPlaceholderText("0") as HTMLInputElement;
    fireEvent.change(input, { target: { value: "8" } });
    await advanceDebounce();
    expect(requests).toEqual([
      { url: "/api/v1/properties/task/99", body: { values: [{ property_id: 5, value: 8 }] } },
    ]);
  });

  it("omits the property from the payload when removed (remove button)", async () => {
    const requests: Array<{ body: unknown }> = [];
    server.use(
      communityHttp.put("/properties/:target/:entityId", async ({ request }) => {
        requests.push({ body: await request.json() });
        return HttpResponse.json([]);
      })
    );

    const props: PropertySummary[] = [
      buildPropertySummary({
        property_id: 3,
        name: "Owner",
        type: PropertyType.text,
        value: "Ada",
      }),
      buildPropertySummary({
        property_id: 4,
        name: "Status",
        type: PropertyType.text,
        value: "Live",
      }),
    ];
    renderWithProviders(
      <PropertyPanel target={PropertyTarget.document} entityId={1} initiativeId={1} saved={props} />
    );

    // The remove buttons carry the "Remove property" aria-label.
    const removeButtons = screen.getAllByRole("button", { name: /Remove property/i });
    // Sort order is alphabetical: Owner, Status. Remove "Owner".
    fireEvent.click(removeButtons[0]);
    await advanceDebounce();

    expect(requests).toHaveLength(1);
    // Status stays, Owner drops out (null value → omitted).
    expect(requests[0].body).toEqual({
      values: [{ property_id: 4, value: "Live" }],
    });
  });

  it("disables the row controls when disabled=true", () => {
    const props: PropertySummary[] = [
      buildPropertySummary({
        property_id: 1,
        name: "Owner",
        type: PropertyType.text,
        value: "Ada",
      }),
    ];
    renderWithProviders(
      <PropertyPanel
        target={PropertyTarget.document}
        entityId={1}
        initiativeId={1}
        saved={props}
        disabled
      />
    );
    expect(screen.getByPlaceholderText("Empty")).toBeDisabled();
    expect(screen.getByRole("button", { name: /Remove property/i })).toBeDisabled();
  });

  it("reconciles the UI when incoming properties change and the field isn't pending", () => {
    const initialProps: PropertySummary[] = [
      buildPropertySummary({
        property_id: 1,
        name: "Owner",
        type: PropertyType.text,
        value: "Initial",
      }),
    ];
    const { rerender } = renderWithProviders(
      <PropertyPanel
        target={PropertyTarget.document}
        entityId={1}
        initiativeId={1}
        saved={initialProps}
      />
    );
    expect((screen.getByPlaceholderText("Empty") as HTMLInputElement).value).toBe("Initial");

    // Server returns a new snapshot.
    const updated: PropertySummary[] = [
      {
        ...initialProps[0],
        value: "Updated",
      },
    ];
    rerender(
      <PropertyPanel
        target={PropertyTarget.document}
        entityId={1}
        initiativeId={1}
        saved={updated}
      />
    );

    expect((screen.getByPlaceholderText("Empty") as HTMLInputElement).value).toBe("Updated");
  });

  it("drops drafts for properties removed from incoming list", () => {
    const full: PropertySummary[] = [
      buildPropertySummary({
        property_id: 1,
        name: "Owner",
        type: PropertyType.text,
        value: "Ada",
      }),
      buildPropertySummary({
        property_id: 2,
        name: "Zeta",
        type: PropertyType.text,
        value: "Hop",
      }),
    ];
    const { rerender } = renderWithProviders(
      <PropertyPanel target={PropertyTarget.document} entityId={1} initiativeId={1} saved={full} />
    );
    expect(screen.getByText("Owner")).toBeInTheDocument();
    expect(screen.getByText("Zeta")).toBeInTheDocument();

    rerender(
      <PropertyPanel
        target={PropertyTarget.document}
        entityId={1}
        initiativeId={1}
        saved={[full[0]]}
      />
    );
    expect(screen.queryByText("Zeta")).not.toBeInTheDocument();
    expect(screen.getByText("Owner")).toBeInTheDocument();
  });

  it("shows the 'no properties' empty state", () => {
    renderWithProviders(
      <PropertyPanel target={PropertyTarget.document} entityId={1} initiativeId={1} saved={[]} />
    );
    expect(screen.getByText(/No properties/i)).toBeInTheDocument();
  });

  it("sends an edit made just before it closes", async () => {
    const writes: { entityId: string; body: unknown }[] = [];
    server.use(
      communityHttp.put("/properties/:target/:entityId", async ({ request, params }) => {
        writes.push({ entityId: String(params.entityId), body: await request.json() });
        return HttpResponse.json([]);
      })
    );
    const property = buildPropertySummary({
      property_id: 1,
      name: "Status",
      type: PropertyType.text,
      value: null,
    });
    const { unmount } = renderWithProviders(
      <PropertyPanel
        target={PropertyTarget.queue_item}
        entityId={4}
        initiativeId={1}
        saved={[property]}
      />
    );

    fireEvent.change(screen.getByPlaceholderText("Empty"), { target: { value: "Ready" } });
    unmount();
    await advanceDebounce();

    expect(writes).toEqual([
      { entityId: "4", body: { values: [{ property_id: 1, value: "Ready" }] } },
    ]);
  });

  it("keeps a row's edit on that row when the panel moves to another", async () => {
    const writes: { entityId: string; body: unknown }[] = [];
    server.use(
      communityHttp.put("/properties/:target/:entityId", async ({ request, params }) => {
        writes.push({ entityId: String(params.entityId), body: await request.json() });
        return HttpResponse.json([]);
      })
    );
    const onFirst = buildPropertySummary({
      property_id: 1,
      name: "Status",
      type: PropertyType.text,
      value: null,
    });
    const onSecond = { ...onFirst, value: "Done" };
    const { rerender } = renderWithProviders(
      <PropertyPanel
        target={PropertyTarget.wiki_page}
        entityId={1}
        saved={[onFirst]}
        initiativeId={3}
      />
    );

    // Typed on the first page, then the second opened before the save.
    fireEvent.change(screen.getByPlaceholderText("Empty"), { target: { value: "Draft" } });
    rerender(
      <PropertyPanel
        target={PropertyTarget.wiki_page}
        entityId={2}
        saved={[onSecond]}
        initiativeId={3}
      />
    );
    await advanceDebounce();

    expect(writes).toEqual([
      { entityId: "1", body: { values: [{ property_id: 1, value: "Draft" }] } },
    ]);
    expect(screen.getByDisplayValue("Done")).toBeInTheDocument();
  });

  it("coalesces rapid edits into a single PUT after the debounce", async () => {
    const requests: Array<{ body: unknown }> = [];
    server.use(
      communityHttp.put("/properties/:target/:entityId", async ({ request }) => {
        requests.push({ body: await request.json() });
        return HttpResponse.json([]);
      })
    );
    const props: PropertySummary[] = [
      buildPropertySummary({
        property_id: 1,
        name: "Owner",
        type: PropertyType.text,
        value: "",
      }),
    ];
    renderWithProviders(
      <PropertyPanel target={PropertyTarget.document} entityId={1} initiativeId={1} saved={props} />
    );
    const input = screen.getByPlaceholderText("Empty") as HTMLInputElement;
    fireEvent.change(input, { target: { value: "A" } });
    await act(async () => {
      vi.advanceTimersByTime(100);
    });
    fireEvent.change(input, { target: { value: "Ada" } });
    await advanceDebounce();
    expect(requests).toHaveLength(1);
    expect(requests[0].body).toEqual({ values: [{ property_id: 1, value: "Ada" }] });
  });

  it("renders definitions with select options so the row reflects the saved value", () => {
    const selectDef = buildPropertySummary({
      property_id: 11,
      name: "Status",
      type: PropertyType.select,
      options: [
        buildPropertyOption({ value: "draft", label: "Draft" }),
        buildPropertyOption({ value: "live", label: "Live" }),
      ],
      value: "live",
    });
    renderWithProviders(
      <PropertyPanel
        target={PropertyTarget.document}
        entityId={1}
        initiativeId={1}
        saved={[selectDef]}
      />
    );
    // Radix Select renders the selected option's label inside the trigger.
    expect(screen.getByText("Live")).toBeInTheDocument();
  });
});
