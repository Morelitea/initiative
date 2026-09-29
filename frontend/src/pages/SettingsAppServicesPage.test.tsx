import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { buildUser } from "@/__tests__/factories";
import { renderPage, renderWithProviders } from "@/__tests__/helpers/render";
import type { AppServiceRegistrationRead } from "@/api/generated/initiativeAPI.schemas";

const buildRegistration = (
  overrides: Partial<AppServiceRegistrationRead> = {}
): AppServiceRegistrationRead => ({
  id: 1,
  public_id: "core.github",
  listing_uid: "gh7k2m9p4q1x8z",
  publisher_id: 1,
  publisher_prefix: "core",
  publisher_name: "Core Apps",
  publisher_enabled: true,
  base_url: "http://initiative-github:8080",
  embed_origin: null,
  allowed_origins: [],
  jwks: { keys: [{ kty: "OKP", crv: "Ed25519", kid: "k1", x: "abc" }] },
  jwks_uri: null,
  scope_ceiling: [],
  mandatory: false,
  enabled: true,
  vendor_fields: [],
  vendor_values: {},
  vendor_set: [],
  vendor_ready: true,
  connection_callback_url: "https://initiative.example.com/api/v1/app-connections/callback",
  connection_setup_url: "https://initiative.example.com/api/v1/app-connections/setup",
  live: true,
  created_at: "2026-08-01T00:00:00.000Z",
  updated_at: "2026-08-12T09:00:00.000Z",
  ...overrides,
});

// Flipped per test before rendering; read lazily inside the mocked hook.
let registrations: AppServiceRegistrationRead[] = [];

const createMutate = vi.fn();
const updateMutate = vi.fn();
const deleteMutate = vi.fn();

vi.mock("@/lib/chesterToast", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

vi.mock("@/hooks/useAppServices", () => ({
  useAppServices: () => ({ data: registrations, isLoading: false, isError: false }),
  useCreateAppService: () => ({ mutate: createMutate, isPending: false }),
  useUpdateAppService: () => ({ mutate: updateMutate, isPending: false }),
  useDeleteAppService: () => ({ mutate: deleteMutate, isPending: false }),
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

  describe("whether an app is live", () => {
    it("labels each registration live or not, with its publisher and listing", () => {
      registrations = [
        buildRegistration({ id: 1, public_id: "core.github", live: true }),
        // No key set, pasted or by address, so it cannot be live.
        buildRegistration({
          id: 2,
          public_id: "core.slack",
          listing_uid: "sl4ck0000000aa",
          jwks: null,
          jwks_uri: null,
          live: false,
        }),
      ];
      renderAsOperator();

      const [github, slack] = screen.getAllByRole("listitem");
      expect(within(github).getByText("Live")).toBeInTheDocument();
      expect(within(github).getByText(/Publisher: Core Apps/)).toBeInTheDocument();
      expect(within(github).getByText("gh7k2m9p4q1x8z")).toBeInTheDocument();
      expect(within(github).queryByText(/Not live until it has signing keys/)).toBeNull();

      expect(within(slack).getByText("Not live")).toBeInTheDocument();
      expect(within(slack).getByText("sl4ck0000000aa")).toBeInTheDocument();
      expect(within(slack).getByText(/Not live until it has signing keys/)).toBeInTheDocument();
    });

    it("says when the publisher is switched off", () => {
      registrations = [
        buildRegistration({ publisher_name: "Acme", publisher_enabled: false, live: false }),
      ];
      renderAsOperator();

      expect(screen.getByText("Not live")).toBeInTheDocument();
      expect(screen.getByText("Publisher switched off")).toBeInTheDocument();
      expect(
        screen.getByText(/Every app from Acme is stopped because its publisher is switched off/)
      ).toBeInTheDocument();
    });

    it("offers no handshake to run", () => {
      registrations = [buildRegistration()];
      renderAsOperator();

      expect(screen.queryByRole("button", { name: "Verify" })).toBeNull();
    });
  });

  describe("reach", () => {
    it("shows mandatory on the registration that carries it", () => {
      registrations = [
        buildRegistration({ id: 1, public_id: "core.automation", mandatory: true }),
        buildRegistration({ id: 2, public_id: "acme.shopify" }),
      ];
      renderAsOperator();

      // Scannable on the row...
      expect(screen.getByText("In every community")).toBeInTheDocument();
      // ...and spelled out, because a reviewer has to know what it means.
      expect(
        screen.getByText(
          "Installed into every community automatically. Community admins cannot remove it or turn it off."
        )
      ).toBeInTheDocument();
    });

    it("confers no powers beyond the scope ceiling", async () => {
      const user = userEvent.setup();
      renderAsOperator();

      await user.click(screen.getByRole("button", { name: "Add app service" }));
      await screen.findByLabelText("App identifier");

      // One switch left in the operator's box: whether every community gets it.
      expect(within(screen.getByRole("dialog")).getAllByRole("switch")).toHaveLength(1);
    });
  });

  describe("registering", () => {
    it("registers a new service with its listing and its keys", async () => {
      const user = userEvent.setup();
      renderAsOperator();

      await user.click(screen.getByRole("button", { name: "Add app service" }));

      await user.type(await screen.findByLabelText("App identifier"), "acme.shopify");
      await user.type(screen.getByLabelText("Listing"), "sh0p1fy0000000");
      await user.type(screen.getByLabelText("Base URL"), "https://shopify.example.com");
      await user.type(
        screen.getByLabelText("Key set address"),
        "https://shopify.example.com/.well-known/jwks.json"
      );
      await user.click(screen.getByRole("button", { name: "Save" }));

      expect(createMutate).toHaveBeenCalledWith(
        {
          public_id: "acme.shopify",
          listing_uid: "sh0p1fy0000000",
          base_url: "https://shopify.example.com",
          // Left blank: the app answers both surfaces at the base URL.
          embed_origin: null,
          allowed_origins: null,
          // Nothing pasted: the keys come from the address.
          jwks: null,
          jwks_uri: "https://shopify.example.com/.well-known/jwks.json",
          mandatory: false,
        },
        expect.anything()
      );
    });

    it("asks for no shared secret", async () => {
      const user = userEvent.setup();
      renderAsOperator();

      await user.click(screen.getByRole("button", { name: "Add app service" }));
      await screen.findByLabelText("App identifier");

      expect(screen.queryByText(/shared secret/i)).toBeNull();
      expect(document.querySelector('input[type="password"]')).toBeNull();
    });

    it("sends the browser address when the app is published somewhere else", async () => {
      const user = userEvent.setup();
      renderAsOperator();

      await user.click(screen.getByRole("button", { name: "Add app service" }));

      await user.type(await screen.findByLabelText("App identifier"), "acme.shopify");
      await user.type(screen.getByLabelText("Listing"), "sh0p1fy0000000");
      await user.type(screen.getByLabelText("Base URL"), "http://shopify:8080");
      await user.type(screen.getByLabelText("Browser address"), "https://shop.example.com");
      await user.click(screen.getByRole("button", { name: "Save" }));

      expect(createMutate).toHaveBeenCalledWith(
        expect.objectContaining({
          base_url: "http://shopify:8080",
          embed_origin: "https://shop.example.com",
        }),
        expect.anything()
      );
    });
  });

  describe("editing", () => {
    it("sends the listing and the key set address, and keeps the pasted set", async () => {
      const user = userEvent.setup();
      registrations = [buildRegistration({ jwks_uri: "https://gh.example.com/jwks.json" })];
      renderAsOperator();

      await user.click(screen.getByRole("button", { name: "Edit" }));
      const listing = await screen.findByLabelText("Listing");
      await user.clear(listing);
      await user.type(listing, "gh0000000000zz");
      // Emptying the address clears it rather than leaving it stored.
      await user.clear(screen.getByLabelText("Key set address"));
      await user.click(screen.getByRole("button", { name: "Save" }));

      const data = updateMutate.mock.calls[0][0].data;
      expect(data).toMatchObject({ listing_uid: "gh0000000000zz", jwks_uri: "" });
      // The stored key set is shown in the box and sent back as it was.
      expect(data.jwks).toEqual(registrations[0].jwks);
      expect(data).not.toHaveProperty("secret");
    });

    it("asks for the vendor values the listing declares, keeping a secret left alone", async () => {
      const user = userEvent.setup();
      registrations = [
        buildRegistration({
          vendor_fields: [
            { key: "client_id", type: "string", required: true, label: { en: "Client id" } },
            { key: "client_secret", type: "secret", required: true, label: { en: "Secret" } },
          ],
          vendor_values: { client_id: "gh-app" },
          vendor_set: ["client_id", "client_secret"],
        }),
      ];
      renderAsOperator();

      await user.click(screen.getByRole("button", { name: "Edit" }));
      const clientId = await screen.findByLabelText(/Client id/);
      expect(clientId).toHaveValue("gh-app");
      // A stored secret is never sent back, only that it is set.
      const secret = screen.getByLabelText(/Secret/);
      expect(secret).toHaveValue("");
      expect(secret).toHaveAttribute("placeholder", "Set. Type to replace it.");
      // Where the vendor sends people back, to register with it.
      expect(screen.getByLabelText("Callback address")).toHaveValue(
        "https://initiative.example.com/api/v1/app-connections/callback"
      );
      expect(screen.getByLabelText("Setup address")).toHaveValue(
        "https://initiative.example.com/api/v1/app-connections/setup"
      );

      await user.clear(clientId);
      await user.type(clientId, "gh-app-2");
      await user.click(screen.getByRole("button", { name: "Save" }));

      expect(updateMutate.mock.calls[0][0].data.vendor_values).toEqual({ client_id: "gh-app-2" });
    });

    it("says a registration waits on its vendor values", () => {
      registrations = [buildRegistration({ vendor_ready: false, live: false })];
      renderAsOperator();

      expect(screen.getByText(/Not live until its vendor client is set/)).toBeInTheDocument();
    });

    it("clears the pasted key set when the box is emptied", async () => {
      const user = userEvent.setup();
      registrations = [buildRegistration()];
      renderAsOperator();

      await user.click(screen.getByRole("button", { name: "Edit" }));
      await user.clear(await screen.findByLabelText("Pasted key set (JWKS)"));
      await user.click(screen.getByRole("button", { name: "Save" }));

      expect(updateMutate.mock.calls[0][0].data.jwks).toEqual({});
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

describe("SettingsPlatformIndexPage", () => {
  it("does not land an apps-only operator on settings they cannot manage", async () => {
    const { SettingsPlatformIndexPage } = await import("@/pages/SettingsPlatformIndexPage");
    renderPage(SettingsPlatformIndexPage, {
      auth: { user: buildUser({ role: "owner", capabilities: ["apps.manage"] }) },
      initialRoute: "/settings/platform",
    });
    // Authentication settings belong to config.manage. Rendering them here
    // would contradict the tab this operator's own capability selects.
    await waitFor(() =>
      expect(screen.queryByRole("heading", { name: /authentication/i })).toBeNull()
    );
  });
});
