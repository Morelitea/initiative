import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

export interface VendorSetupSearch {
  code?: string;
  state?: string;
}

const text = (value: unknown): string | undefined =>
  typeof value === "string" && value ? value.slice(0, 200) : undefined;

export const Route = createFileRoute(
  "/_serverRequired/_authenticated/settings/platform/integrations_/vendor-setup/$registrationId"
)({
  // Where a vendor's setup sends the operator back, with its code and the
  // state the setup started with.
  validateSearch: (search: Record<string, unknown>): VendorSetupSearch => ({
    code: text(search.code),
    state: text(search.state),
  }),
  component: lazyRouteComponent(() =>
    import("@/pages/SettingsVendorSetupPage").then((m) => ({
      default: m.SettingsVendorSetupPage,
    }))
  ),
});
