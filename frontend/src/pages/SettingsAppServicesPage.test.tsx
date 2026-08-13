import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { buildUser } from "@/__tests__/factories";
import { renderWithProviders } from "@/__tests__/helpers/render";
import type { AppServiceRegistrationRead } from "@/api/generated/initiativeAPI.schemas";

const buildRegistration = (
  overrides: Partial<AppServiceRegistrationRead> = {}
): AppServiceRegistrationRead => ({
  id: 1,
  public_id: "core.github",
  listing_uid: null,
  base_url: "http://initiative-github:8080",
  allowed_origins: [],
  has_secret: true,
  manifest_hash: "abc123",
  protocol_version: 1,
  grants: [],
  mandatory: false,
  enabled: true,
  status: "ok",
  last_verified_at: "2026-08-12T09:00:00.000Z",
  created_at: "2026-08-01T00:00:00.000Z",
  updated_at: "2026-08-12T09:00:00.000Z",
  ...overrides,
});

// Flipped per test before rendering; read lazily inside the mocked hook.
let registrations: AppServiceRegistrationRead[] = [];

const createMutate = vi.fn();
const updateMutate = vi.fn();
const deleteMutate = vi.fn();
const verifyMutate = vi.fn();

vi.mock("@/lib/chesterToast", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

vi.mock("@/hooks/useAppServices", () => ({
  useAppServices: () => ({ data: registrations, isLoading: false, isError: false }),
  useCreateAppService: () => ({ mutate: createMutate, isPending: false }),
  useUpdateAppService: () => ({ mutate: updateMutate, isPending: false }),
  useDeleteAppService: () => ({ mutate: deleteMutate, isPending: false }),
  useVerifyAppService: () => ({ mutate: verifyMutate, isPending: false, variables: undefined }),
}));

import { SettingsAppServicesPage } from "./SettingsAppServicesPage";

const renderAsOperator = () =>
  renderWithProviders(<SettingsAppServicesPage />, {
    auth: { user: buildUser({ role: "owner", capabilities: ["apps.manage"] }) },
  });

describe("SettingsAppServicesPage", () => {
  beforeEach(() => {
    registrations = [];
    createMutate.mockReset();
    updateMutate.mockReset();
    deleteMutate.mockReset();
    verifyMutate.mockReset();
  });

  describe("capability gate", () => {
    it("offers nothing to manage without apps.manage", () => {
      registrations = [buildRegistration()];
      // A platform owner still sees nothing: the gate is the capability, never
      // the role.
      renderWithProviders(<SettingsAppServicesPage />, {
        auth: { user: buildUser({ role: "owner", capabilities: [] }) },
      });

      expect(screen.getByText("Only platform owners can manage app services.")).toBeInTheDocument();
      expect(screen.queryByRole("button", { name: "Add app service" })).toBeNull();
      expect(screen.queryByText("core.github")).toBeNull();
    });
  });

  describe("status", () => {
    it("labels every verification state, and says when one was last checked", () => {
      registrations = [
        buildRegistration({ id: 1, public_id: "a.ok", status: "ok" }),
        // A registration that has never answered: no timestamp, and no
        // protocol version either, so the meta line reads exactly "Never
        // verified".
        buildRegistration({
          id: 2,
          public_id: "a.new",
          status: "unverified",
          last_verified_at: null,
          protocol_version: null,
        }),
        buildRegistration({ id: 3, public_id: "a.down", status: "unreachable" }),
        buildRegistration({ id: 4, public_id: "a.wrongkey", status: "signature_mismatch" }),
      ];
      renderAsOperator();

      expect(screen.getByText("Verified")).toBeInTheDocument();
      expect(screen.getByText("Not verified")).toBeInTheDocument();
      expect(screen.getByText("Unreachable")).toBeInTheDocument();
      expect(screen.getByText("Secret mismatch")).toBeInTheDocument();
      expect(screen.getByText("Never verified")).toBeInTheDocument();
    });
  });

  describe("operator-conferred powers", () => {
    it("shows mandatory and delegation on the registration that carries them", () => {
      registrations = [
        buildRegistration({
          id: 1,
          public_id: "core.automation",
          mandatory: true,
          grants: ["delegation"],
        }),
        buildRegistration({ id: 2, public_id: "acme.shopify" }),
      ];
      renderAsOperator();

      // Scannable on the row...
      expect(screen.getByText("In every guild")).toBeInTheDocument();
      expect(screen.getByText("Acts as members")).toBeInTheDocument();
      // ...and spelled out, because a reviewer has to know what they mean.
      expect(
        screen.getByText(
          "Installed into every guild automatically. Guild admins cannot remove it or turn it off."
        )
      ).toBeInTheDocument();
      expect(
        screen.getByText(
          "This app may call the API as a real member, under that member's own permissions."
        )
      ).toBeInTheDocument();
    });
  });

  describe("the shared secret", () => {
    it("is never displayed — only reported as stored, and replaceable", async () => {
      const user = userEvent.setup();
      registrations = [buildRegistration({ has_secret: true })];
      renderAsOperator();

      await user.click(screen.getByRole("button", { name: "Edit" }));

      expect(
        await screen.findByText("A shared secret is stored for this app.")
      ).toBeInTheDocument();
      // With one already stored there is no input at all until the operator
      // asks to replace it, so there is nothing that could show a value.
      expect(screen.queryByPlaceholderText("Paste the app's INITIATIVE_APP_SECRET")).toBeNull();

      await user.click(screen.getByLabelText("Replace the shared secret"));

      const secretInput = screen.getByPlaceholderText(
        "Paste the app's INITIATIVE_APP_SECRET"
      ) as HTMLInputElement;
      expect(secretInput).toHaveAttribute("type", "password");
      expect(secretInput.value).toBe("");
    });

    it("registers a new service with the secret and the powers the operator chose", async () => {
      const user = userEvent.setup();
      renderAsOperator();

      await user.click(screen.getByRole("button", { name: "Add app service" }));

      await user.type(await screen.findByLabelText("App identifier"), "acme.shopify");
      await user.type(screen.getByLabelText("Base URL"), "http://shopify:8080");
      await user.type(
        screen.getByPlaceholderText("Paste the app's INITIATIVE_APP_SECRET"),
        "s3cret"
      );
      await user.click(screen.getByRole("switch", { name: "Act as members (delegation)" }));
      await user.click(screen.getByRole("button", { name: "Save" }));

      expect(createMutate).toHaveBeenCalledWith(
        {
          base_url: "http://shopify:8080",
          secret: "s3cret",
          public_id: "acme.shopify",
          allowed_origins: null,
          grants: ["delegation"],
          mandatory: false,
        },
        expect.anything()
      );
    });
  });

  describe("the operator kill switch", () => {
    it("confirms before stopping an app, and says what stopping means", async () => {
      const user = userEvent.setup();
      registrations = [buildRegistration()];
      renderAsOperator();

      await user.click(screen.getByRole("switch"));

      // Nothing has happened yet.
      expect(updateMutate).not.toHaveBeenCalled();

      const dialog = await screen.findByRole("alertdialog");
      expect(within(dialog).getByText("Disable core.github?")).toBeInTheDocument();
      expect(within(dialog).getByText(/stops reaching it immediately/)).toBeInTheDocument();
      expect(within(dialog).getByText(/Nothing is deleted/)).toBeInTheDocument();

      await user.click(within(dialog).getByRole("button", { name: "Disable app service" }));

      expect(updateMutate).toHaveBeenCalledWith(
        { registrationId: 1, data: { enabled: false } },
        expect.anything()
      );
    });

    it("turns an app back on without a confirmation", async () => {
      const user = userEvent.setup();
      registrations = [buildRegistration({ enabled: false })];
      renderAsOperator();

      await user.click(screen.getByRole("switch"));

      expect(screen.queryByRole("alertdialog")).toBeNull();
      expect(updateMutate).toHaveBeenCalledWith(
        { registrationId: 1, data: { enabled: true } },
        expect.anything()
      );
    });
  });

  describe("verify", () => {
    it("surfaces a changed manifest instead of accepting it silently", async () => {
      const user = userEvent.setup();
      const registration = buildRegistration({ status: "manifest_mismatch" });
      registrations = [registration];

      verifyMutate.mockImplementation((variables, options) => {
        if (variables.data?.accept_manifest_change) options?.onSuccess?.(registration);
        else
          options?.onError?.({
            response: { data: { detail: "APP_SERVICE_MANIFEST_CHANGED" } },
          });
      });

      renderAsOperator();

      await user.click(screen.getByRole("button", { name: "Verify" }));

      // The first attempt never offers to adopt a new manifest on its own.
      expect(verifyMutate.mock.calls[0][0]).toEqual({ registrationId: 1, data: undefined });

      const dialog = await screen.findByRole("alertdialog");
      expect(
        within(dialog).getByText("core.github now describes itself differently")
      ).toBeInTheDocument();

      await user.click(within(dialog).getByRole("button", { name: "Accept the new manifest" }));

      expect(verifyMutate.mock.calls[1][0]).toEqual({
        registrationId: 1,
        data: { accept_manifest_change: true },
      });
    });
  });

  describe("delete", () => {
    it("names what is lost and holds out for the app identifier", async () => {
      const user = userEvent.setup();
      registrations = [buildRegistration()];
      renderAsOperator();

      await user.click(screen.getByRole("button", { name: "Delete" }));

      const dialog = await screen.findByRole("alertdialog");
      expect(within(dialog).getByText(/removed for good/)).toBeInTheDocument();

      const confirm = within(dialog).getByRole("button", { name: "Delete" });
      expect(confirm).toBeDisabled();

      await user.type(
        within(dialog).getByLabelText("Type the app identifier to confirm"),
        "core.github"
      );
      await user.click(confirm);

      expect(deleteMutate).toHaveBeenCalledWith(1, expect.anything());
    });
  });
});
