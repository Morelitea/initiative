import { fireEvent, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { renderWithProviders } from "@/__tests__/helpers/render";
import type { AuthProviderAdminRead } from "@/api/generated/initiativeAPI.schemas";

const createMutate = vi.fn();
const updateMutate = vi.fn();
const deleteMutate = vi.fn();

let providersData: AuthProviderAdminRead[] = [];

vi.mock("@/hooks/useSettings", () => ({
  useAuthProviders: () => ({ data: providersData, isLoading: false }),
  useCreateAuthProvider: () => ({ mutate: createMutate, isPending: false }),
  useUpdateAuthProvider: () => ({ mutate: updateMutate, isPending: false }),
  useDeleteAuthProvider: () => ({ mutate: deleteMutate, isPending: false }),
}));

import { AuthProvidersSection } from "./AuthProvidersSection";

const platformRow: AuthProviderAdminRead = {
  id: 1,
  slug: "oidc",
  display_name: "Okta",
  kind: "oidc",
  enabled: true,
  issuer: "https://idp.example.com",
  client_id: "client-1",
  scopes: "openid email",
  role_claim_path: null,
  allow_jit: true,
  icon: null,
  button_style: null,
  secret_set: true,
  callback_url: "https://app.example.com/api/v1/auth/oidc/callback",
};

const corpRow: AuthProviderAdminRead = {
  ...platformRow,
  id: 2,
  slug: "corp",
  display_name: "Corp SSO",
  secret_set: true,
  callback_url: "https://app.example.com/api/v1/auth/corp/callback",
};

const rowFor = (name: string) => screen.getByText(name).closest("li") as HTMLElement;

describe("AuthProvidersSection", () => {
  beforeEach(() => {
    createMutate.mockClear();
    updateMutate.mockClear();
    deleteMutate.mockClear();
    providersData = [platformRow, corpRow];
  });

  it("offers every provider the same actions", () => {
    renderWithProviders(<AuthProvidersSection />);

    // The row an install started with is a row. Two providers, two of each.
    expect(screen.getAllByRole("button", { name: "Edit" })).toHaveLength(2);
    expect(screen.getAllByRole("button", { name: "Delete" })).toHaveLength(2);
  });

  it("shows each provider the address its IdP sends the browser back to", () => {
    renderWithProviders(<AuthProvidersSection />);

    // The address follows the slug, and this row is where the page states it —
    // which is what an operator registers with their IdP.
    expect(
      screen.getByText("https://app.example.com/api/v1/auth/oidc/callback")
    ).toBeInTheDocument();
    expect(
      screen.getByText("https://app.example.com/api/v1/auth/corp/callback")
    ).toBeInTheDocument();
  });

  it("creates a provider from the dialog form", async () => {
    renderWithProviders(<AuthProvidersSection />);

    fireEvent.click(screen.getByRole("button", { name: "Add provider" }));
    fireEvent.change(await screen.findByLabelText("Slug"), {
      target: { value: "acme" },
    });
    fireEvent.change(screen.getByLabelText("Display name"), {
      target: { value: "Acme ID" },
    });
    fireEvent.change(screen.getByLabelText("Issuer URL"), {
      target: { value: "https://id.acme.example" },
    });
    fireEvent.change(screen.getByLabelText("Client ID"), {
      target: { value: "acme-client" },
    });
    fireEvent.change(screen.getByLabelText("Client secret"), {
      target: { value: "acme-secret" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));

    expect(createMutate).toHaveBeenCalledTimes(1);
    expect(createMutate.mock.calls[0][0]).toMatchObject({
      slug: "acme",
      display_name: "Acme ID",
      issuer: "https://id.acme.example",
      client_id: "acme-client",
      client_secret: "acme-secret",
      enabled: true,
      allow_jit: true,
    });
  });

  it("keeps the stored secret when the edit form leaves it blank", async () => {
    renderWithProviders(<AuthProvidersSection />);

    fireEvent.click(within(rowFor("Corp SSO")).getByRole("button", { name: "Edit" }));
    const secret = (await screen.findByLabelText("Client secret")) as HTMLInputElement;
    expect(secret.value).toBe("");
    expect(secret.placeholder).toMatch(/keep the current secret/i);
    fireEvent.change(screen.getByLabelText("Display name"), {
      target: { value: "Corp Renamed" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));

    expect(updateMutate).toHaveBeenCalledTimes(1);
    const call = updateMutate.mock.calls[0][0];
    expect(call.providerId).toBe(2);
    expect(call.data.display_name).toBe("Corp Renamed");
    expect("client_secret" in call.data).toBe(false);
  });

  it("shows the slug error on invalid submit and clears it on reopen", async () => {
    renderWithProviders(<AuthProvidersSection />);

    fireEvent.click(screen.getByRole("button", { name: "Add provider" }));
    fireEvent.change(await screen.findByLabelText("Slug"), {
      target: { value: "bad-" },
    });
    fireEvent.change(screen.getByLabelText("Display name"), {
      target: { value: "Bad" },
    });
    fireEvent.change(screen.getByLabelText("Issuer URL"), {
      target: { value: "https://id.example" },
    });
    fireEvent.change(screen.getByLabelText("Client ID"), {
      target: { value: "c" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));

    expect(createMutate).not.toHaveBeenCalled();
    expect(screen.getByText(/no leading or trailing dash/i)).toBeInTheDocument();

    // Typing clears the error…
    fireEvent.change(screen.getByLabelText("Slug"), { target: { value: "bad" } });
    expect(screen.queryByText(/no leading or trailing dash/i)).not.toBeInTheDocument();

    // …and a stale error never survives a close/reopen.
    fireEvent.change(screen.getByLabelText("Slug"), { target: { value: "bad-" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(screen.getByText(/no leading or trailing dash/i)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    fireEvent.click(screen.getByRole("button", { name: "Add provider" }));
    expect(await screen.findByLabelText("Slug")).toBeInTheDocument();
    expect(screen.queryByText(/no leading or trailing dash/i)).not.toBeInTheDocument();
  });

  it("deletes after confirmation", async () => {
    renderWithProviders(<AuthProvidersSection />);

    fireEvent.click(within(rowFor("Corp SSO")).getByRole("button", { name: "Delete" }));
    const dialog = await screen.findByRole("alertdialog");
    fireEvent.click(within(dialog).getByRole("button", { name: "Delete" }));

    expect(deleteMutate).toHaveBeenCalledTimes(1);
    expect(deleteMutate.mock.calls[0][0]).toBe(2);
  });
});
