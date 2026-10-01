import { act, fireEvent, screen } from "@testing-library/react";
import { HttpResponse } from "msw";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { buildPropertyOption, buildPropertySummary } from "@/__tests__/factories/properties";
import { guildHttp } from "@/__tests__/helpers/guildHttp";
import { server } from "@/__tests__/helpers/msw-server";
import { renderWithProviders } from "@/__tests__/helpers/render";
import {
  type PropertySummary,
  PropertyTarget,
  PropertyType,
} from "@/api/generated/initiativeAPI.schemas";

import { PropertyList } from "./PropertyList";

describe("PropertyList", () => {
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
      <PropertyList target={PropertyTarget.document} entityId={10} properties={properties} />
    );
    expect(screen.getByText("Status")).toBeInTheDocument();
    expect(screen.getByText("Owner")).toBeInTheDocument();
  });

  it("attaches an added property without writing over a value just entered", async () => {
    const bodies: unknown[] = [];
    server.use(
      guildHttp.put("/properties/:target/:entityId", async ({ request }) => {
        bodies.push(await request.json());
        return HttpResponse.json([]);
      })
    );
    const first = buildPropertySummary({
      property_id: 1,
      name: "Status",
      type: PropertyType.text,
      value: null,
    });
    const second = buildPropertySummary({
      property_id: 2,
      name: "Owner",
      type: PropertyType.text,
      value: null,
    });
    const { rerender } = renderWithProviders(
      <PropertyList
        target={PropertyTarget.calendar_event}
        entityId={9}
        properties={[first]}
        unsaved={[1]}
      />
    );
    await advanceDebounce();
    expect(bodies).toEqual([{ values: [{ property_id: 1, value: null }] }]);

    // Filled in, then another added before the row comes back from the server.
    fireEvent.change(screen.getByPlaceholderText("Empty"), { target: { value: "Ready" } });
    rerender(
      <PropertyList
        target={PropertyTarget.calendar_event}
        entityId={9}
        properties={[first, second]}
        unsaved={[1, 2]}
      />
    );
    await advanceDebounce();

    expect(bodies).toHaveLength(2);
    expect(bodies[1]).toEqual({
      values: [
        { property_id: 1, value: "Ready" },
        { property_id: 2, value: null },
      ],
    });
  });

  it("writes the values through the one route after the debounce when a value changes", async () => {
    const requests: Array<{ url: string; body: unknown }> = [];
    server.use(
      guildHttp.put("/properties/:target/:entityId", async ({ request, params }) => {
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
      <PropertyList target={PropertyTarget.document} entityId={7} properties={props} />
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
      guildHttp.put("/properties/:target/:entityId", async ({ request }) => {
        requests.push({ body: await request.json() });
        return HttpResponse.json([]);
      })
    );

    const props: PropertySummary[] = [
      buildPropertySummary({
        property_id: 1,
        name: "Reviewer",
        type: PropertyType.user_reference,
        value: { id: 7, full_name: "Grace" },
      }),
      buildPropertySummary({ property_id: 2, name: "Owner", type: PropertyType.text, value: "" }),
    ];
    renderWithProviders(
      <PropertyList target={PropertyTarget.document} entityId={1} properties={props} />
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
      guildHttp.put("/properties/:target/:entityId", async ({ request, params }) => {
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
      <PropertyList target={PropertyTarget.task} entityId={99} properties={props} />
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
      guildHttp.put("/properties/:target/:entityId", async ({ request }) => {
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
      <PropertyList target={PropertyTarget.document} entityId={1} properties={props} />
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
      <PropertyList target={PropertyTarget.document} entityId={1} properties={props} disabled />
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
      <PropertyList target={PropertyTarget.document} entityId={1} properties={initialProps} />
    );
    expect((screen.getByPlaceholderText("Empty") as HTMLInputElement).value).toBe("Initial");

    // Server returns a new snapshot.
    const updated: PropertySummary[] = [
      {
        ...initialProps[0],
        value: "Updated",
      },
    ];
    rerender(<PropertyList target={PropertyTarget.document} entityId={1} properties={updated} />);

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
      <PropertyList target={PropertyTarget.document} entityId={1} properties={full} />
    );
    expect(screen.getByText("Owner")).toBeInTheDocument();
    expect(screen.getByText("Zeta")).toBeInTheDocument();

    rerender(<PropertyList target={PropertyTarget.document} entityId={1} properties={[full[0]]} />);
    expect(screen.queryByText("Zeta")).not.toBeInTheDocument();
    expect(screen.getByText("Owner")).toBeInTheDocument();
  });

  it("shows the 'no properties' empty state", () => {
    renderWithProviders(
      <PropertyList target={PropertyTarget.document} entityId={1} properties={[]} />
    );
    expect(screen.getByText(/No properties/i)).toBeInTheDocument();
  });

  it("coalesces rapid edits into a single PUT after the debounce", async () => {
    const requests: Array<{ body: unknown }> = [];
    server.use(
      guildHttp.put("/properties/:target/:entityId", async ({ request }) => {
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
      <PropertyList target={PropertyTarget.document} entityId={1} properties={props} />
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
      <PropertyList target={PropertyTarget.document} entityId={1} properties={[selectDef]} />
    );
    // Radix Select renders the selected option's label inside the trigger.
    expect(screen.getByText("Live")).toBeInTheDocument();
  });
});
