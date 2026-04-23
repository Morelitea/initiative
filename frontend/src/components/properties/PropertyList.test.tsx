import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { act, fireEvent, screen } from "@testing-library/react";
import { http, HttpResponse } from "msw";

import { renderWithProviders } from "@/__tests__/helpers/render";
import { server } from "@/__tests__/helpers/msw-server";
import { buildPropertyOption, buildPropertySummary } from "@/__tests__/factories/properties";
import { PropertyType, type PropertySummary } from "@/api/generated/initiativeAPI.schemas";

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
      <PropertyList entityKind="document" entityId={10} properties={properties} />
    );
    expect(screen.getByText("Status")).toBeInTheDocument();
    expect(screen.getByText("Owner")).toBeInTheDocument();
  });

  it("calls the document set-values mutation after the debounce when a value changes", async () => {
    const requests: Array<{ url: string; body: unknown }> = [];
    server.use(
      http.put("/api/v1/documents/:documentId/properties", async ({ request, params }) => {
        requests.push({
          url: `/api/v1/documents/${params.documentId}/properties`,
          body: await request.json(),
        });
        return HttpResponse.json({ id: Number(params.documentId), properties: [] });
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
    renderWithProviders(<PropertyList entityKind="document" entityId={7} properties={props} />);

    const input = screen.getByPlaceholderText("Empty") as HTMLInputElement;
    fireEvent.change(input, { target: { value: "Ada" } });

    // Before the debounce fires we should have no network calls yet.
    expect(requests).toHaveLength(0);
    await advanceDebounce();

    // One PUT with the changed value.
    expect(requests).toHaveLength(1);
    expect(requests[0].url).toBe("/api/v1/documents/7/properties");
    expect(requests[0].body).toEqual({ values: [{ property_id: 42, value: "Ada" }] });
  });

  it("fires the task mutation when entityKind is 'task'", async () => {
    const requests: Array<{ url: string }> = [];
    server.use(
      http.put("/api/v1/tasks/:taskId/properties", async ({ params }) => {
        requests.push({ url: `/api/v1/tasks/${params.taskId}/properties` });
        return HttpResponse.json({ id: Number(params.taskId), properties: [] });
      })
    );

    const props: PropertySummary[] = [
      buildPropertySummary({ property_id: 5, name: "Hours", type: PropertyType.number, value: 1 }),
    ];
    renderWithProviders(<PropertyList entityKind="task" entityId={99} properties={props} />);

    const input = screen.getByPlaceholderText("0") as HTMLInputElement;
    fireEvent.change(input, { target: { value: "8" } });
    await advanceDebounce();
    expect(requests).toEqual([{ url: "/api/v1/tasks/99/properties" }]);
  });

  it("omits the property from the payload when removed (remove button)", async () => {
    const requests: Array<{ body: unknown }> = [];
    server.use(
      http.put("/api/v1/documents/:documentId/properties", async ({ request }) => {
        requests.push({ body: await request.json() });
        return HttpResponse.json({ properties: [] });
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
    renderWithProviders(<PropertyList entityKind="document" entityId={1} properties={props} />);

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
      <PropertyList entityKind="document" entityId={1} properties={props} disabled />
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
      <PropertyList entityKind="document" entityId={1} properties={initialProps} />
    );
    expect((screen.getByPlaceholderText("Empty") as HTMLInputElement).value).toBe("Initial");

    // Server returns a new snapshot.
    const updated: PropertySummary[] = [
      {
        ...initialProps[0],
        value: "Updated",
      },
    ];
    rerender(<PropertyList entityKind="document" entityId={1} properties={updated} />);

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
      <PropertyList entityKind="document" entityId={1} properties={full} />
    );
    expect(screen.getByText("Owner")).toBeInTheDocument();
    expect(screen.getByText("Zeta")).toBeInTheDocument();

    rerender(<PropertyList entityKind="document" entityId={1} properties={[full[0]]} />);
    expect(screen.queryByText("Zeta")).not.toBeInTheDocument();
    expect(screen.getByText("Owner")).toBeInTheDocument();
  });

  it("shows the 'no properties' empty state", () => {
    renderWithProviders(<PropertyList entityKind="document" entityId={1} properties={[]} />);
    expect(screen.getByText(/No properties/i)).toBeInTheDocument();
  });

  it("coalesces rapid edits into a single PUT after the debounce", async () => {
    const requests: Array<{ body: unknown }> = [];
    server.use(
      http.put("/api/v1/documents/:documentId/properties", async ({ request }) => {
        requests.push({ body: await request.json() });
        return HttpResponse.json({ properties: [] });
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
    renderWithProviders(<PropertyList entityKind="document" entityId={1} properties={props} />);
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
      <PropertyList entityKind="document" entityId={1} properties={[selectDef]} />
    );
    // Radix Select renders the selected option's label inside the trigger.
    expect(screen.getByText("Live")).toBeInTheDocument();
  });
});
