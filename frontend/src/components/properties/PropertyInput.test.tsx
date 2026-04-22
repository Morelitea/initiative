import { describe, expect, it, vi } from "vitest";
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";

import { renderWithProviders } from "@/__tests__/helpers/render";
import { server } from "@/__tests__/helpers/msw-server";
import { buildPropertyDefinition, buildPropertyOption } from "@/__tests__/factories/properties";
import {
  PropertyAppliesTo,
  PropertyType,
  type PropertyDefinitionRead,
} from "@/api/generated/initiativeAPI.schemas";

import { PropertyInput } from "./PropertyInput";

const def = (overrides: Partial<PropertyDefinitionRead>) =>
  buildPropertyDefinition({ applies_to: PropertyAppliesTo.both, ...overrides });

describe("PropertyInput", () => {
  describe("text type", () => {
    it("renders an <input type='text'> and calls onChange with the string", async () => {
      const onChange = vi.fn();
      renderWithProviders(
        <PropertyInput
          definition={def({ type: PropertyType.text, name: "Owner" })}
          value=""
          onChange={onChange}
        />
      );
      const input = screen.getByPlaceholderText("Empty") as HTMLInputElement;
      expect(input.type).toBe("text");
      await userEvent.type(input, "a");
      expect(onChange).toHaveBeenLastCalledWith("a");
    });
  });

  describe("number type", () => {
    it("renders an <input type='number'> and parses '42' into a number", () => {
      const onChange = vi.fn();
      renderWithProviders(
        <PropertyInput
          definition={def({ type: PropertyType.number, name: "Count" })}
          value={null}
          onChange={onChange}
        />
      );
      const input = screen.getByPlaceholderText("0") as HTMLInputElement;
      expect(input.type).toBe("number");
      // userEvent.type doesn't support fractional/full-value in a single call well
      // for type=number; fire change directly to mirror user entering 42.
      fireEvent.change(input, { target: { value: "42" } });
      expect(onChange).toHaveBeenCalledWith(42);
    });
  });

  describe("checkbox type", () => {
    it("renders a checkbox and toggles onChange(true)", async () => {
      const onChange = vi.fn();
      renderWithProviders(
        <PropertyInput
          definition={def({ type: PropertyType.checkbox, name: "Done" })}
          value={false}
          onChange={onChange}
        />
      );
      const checkbox = screen.getByRole("checkbox");
      await userEvent.click(checkbox);
      expect(onChange).toHaveBeenCalledWith(true);
    });
  });

  describe("date type", () => {
    it("renders a DateTimePicker (includeTime=false)", () => {
      renderWithProviders(
        <PropertyInput
          definition={def({ type: PropertyType.date, name: "Deadline" })}
          value=""
          onChange={vi.fn()}
        />
      );
      // DateTimePicker renders a button with "Pick a date" placeholder when no value.
      expect(screen.getByRole("button", { name: /pick a date/i })).toBeInTheDocument();
    });
  });

  describe("datetime type", () => {
    it("renders a DateTimePicker with time support", () => {
      renderWithProviders(
        <PropertyInput
          definition={def({ type: PropertyType.datetime, name: "When" })}
          value=""
          onChange={vi.fn()}
        />
      );
      expect(screen.getByRole("button", { name: /pick a date and time/i })).toBeInTheDocument();
    });
  });

  describe("url type", () => {
    it("renders an <input type='url'> and propagates the value", () => {
      const onChange = vi.fn();
      renderWithProviders(
        <PropertyInput
          definition={def({ type: PropertyType.url, name: "Website" })}
          value=""
          onChange={onChange}
        />
      );
      const input = screen.getByPlaceholderText("https://…") as HTMLInputElement;
      expect(input.type).toBe("url");
      fireEvent.change(input, { target: { value: "https://example.com" } });
      expect(onChange).toHaveBeenCalledWith("https://example.com");
    });
  });

  describe("select type", () => {
    const selectDef = def({
      type: PropertyType.select,
      name: "Status",
      options: [
        buildPropertyOption({ value: "draft", label: "Draft" }),
        buildPropertyOption({ value: "live", label: "Live" }),
      ],
    });

    it("renders the options and fires onChange with the option slug when picked", async () => {
      const onChange = vi.fn();
      renderWithProviders(<PropertyInput definition={selectDef} value="" onChange={onChange} />);
      const trigger = screen.getByRole("combobox");
      await userEvent.click(trigger);
      const liveOption = await screen.findByRole("option", { name: "Live" });
      await userEvent.click(liveOption);
      expect(onChange).toHaveBeenCalledWith("live");
    });

    it("renders fallback 'Unknown option' text when value is not in definition.options", () => {
      renderWithProviders(
        <PropertyInput definition={selectDef} value="archived" onChange={vi.fn()} />
      );
      expect(screen.getByText(/Unknown option: archived/i)).toBeInTheDocument();
    });
  });

  describe("multi_select type", () => {
    it("renders a multi-select and emits an array of slugs on change", async () => {
      const multiDef = def({
        type: PropertyType.multi_select,
        name: "Tags",
        options: [
          buildPropertyOption({ value: "alpha", label: "Alpha" }),
          buildPropertyOption({ value: "beta", label: "Beta" }),
        ],
      });
      const onChange = vi.fn();
      renderWithProviders(<PropertyInput definition={multiDef} value={[]} onChange={onChange} />);
      const trigger = screen.getByRole("combobox");
      await userEvent.click(trigger);
      const alphaOption = await screen.findByRole("option", { name: /Alpha/i });
      // MultiSelect uses pointer events to toggle; fire them to drive the
      // onPointerUp handler that actually calls toggleValue.
      fireEvent.pointerDown(alphaOption);
      fireEvent.pointerUp(alphaOption);
      expect(onChange).toHaveBeenCalledWith(["alpha"]);
    });
  });

  describe("user_reference type", () => {
    it("renders a user picker combobox backed by the users API", async () => {
      // Seed a user so the combobox has items; useUsers returns UserGuildMember[].
      server.use(
        http.get("/api/v1/users/", () =>
          HttpResponse.json([
            { id: 7, full_name: "Ada Lovelace", email: "ada@example.com" },
            { id: 8, full_name: "Grace Hopper", email: "grace@example.com" },
          ])
        )
      );
      renderWithProviders(
        <PropertyInput
          definition={def({ type: PropertyType.user_reference, name: "Owner" })}
          value={null}
          onChange={vi.fn()}
        />
      );
      const trigger = screen.getByRole("combobox");
      expect(trigger).toBeInTheDocument();
      // Wait for users to load and render in the popover after we open it.
      await userEvent.click(trigger);
      await waitFor(() =>
        expect(screen.getByRole("option", { name: /Ada Lovelace/i })).toBeInTheDocument()
      );
    });
  });

  describe("disabled prop", () => {
    it("disables a text input", () => {
      renderWithProviders(
        <PropertyInput
          definition={def({ type: PropertyType.text })}
          value=""
          onChange={vi.fn()}
          disabled
        />
      );
      expect(screen.getByPlaceholderText("Empty")).toBeDisabled();
    });

    it("disables a checkbox", () => {
      renderWithProviders(
        <PropertyInput
          definition={def({ type: PropertyType.checkbox })}
          value={false}
          onChange={vi.fn()}
          disabled
        />
      );
      expect(screen.getByRole("checkbox")).toBeDisabled();
    });

    it("disables a select trigger", () => {
      renderWithProviders(
        <PropertyInput
          definition={def({
            type: PropertyType.select,
            options: [buildPropertyOption({ value: "a", label: "A" })],
          })}
          value=""
          onChange={vi.fn()}
          disabled
        />
      );
      // Radix Select disables the trigger via data attr + aria-disabled.
      const trigger = screen.getByRole("combobox");
      expect(trigger).toBeDisabled();
    });

    it("disables a number input", () => {
      renderWithProviders(
        <PropertyInput
          definition={def({ type: PropertyType.number })}
          value={null}
          onChange={vi.fn()}
          disabled
        />
      );
      expect(screen.getByPlaceholderText("0")).toBeDisabled();
    });
  });

  describe("summary-shape definitions", () => {
    it("accepts a PropertySummary (no id/guild_id) as definition", () => {
      renderWithProviders(
        <PropertyInput
          definition={{
            property_id: 9,
            name: "Lite",
            type: PropertyType.text,
            applies_to: PropertyAppliesTo.both,
            options: null,
            value: null,
          }}
          value="hello"
          onChange={vi.fn()}
        />
      );
      expect(screen.getByDisplayValue("hello")).toBeInTheDocument();
    });
  });

  describe("select options rendering", () => {
    it("shows each option label in the dropdown", async () => {
      const multi = def({
        type: PropertyType.select,
        options: [
          buildPropertyOption({ value: "one", label: "One" }),
          buildPropertyOption({ value: "two", label: "Two" }),
        ],
      });
      renderWithProviders(<PropertyInput definition={multi} value="" onChange={vi.fn()} />);
      const trigger = screen.getByRole("combobox");
      await userEvent.click(trigger);
      const listbox = await screen.findByRole("listbox");
      expect(within(listbox).getByRole("option", { name: "One" })).toBeInTheDocument();
      expect(within(listbox).getByRole("option", { name: "Two" })).toBeInTheDocument();
    });
  });
});
