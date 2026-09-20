/**
 * The identity providers worth offering by name, and how each one spells its
 * issuer.
 *
 * Every one of these takes the same four values, so what a preset is actually
 * worth is the issuer: it is the field people get wrong, it differs per
 * provider in ways their own docs bury, and two of them need a value from the
 * far end (a realm, a tenant) that nobody should be hand-editing into the
 * middle of a URL. So the template names its own blanks, the form asks for
 * each blank as a field, and the address is built rather than typed.
 *
 * Kept in step with the quickstarts in `docs/en/admin/single-sign-on.md`: the
 * list came from there, and a change to either belongs in both.
 */

/** The labels `settings:authProviders.blanks` carries. Closed, so a preset
 *  naming one that is not there fails to compile rather than at render. */
export type BlankLabelKey = "tenant" | "oktaHost" | "auth0Host" | "host" | "realm" | "application";

/** Likewise for `settings:authProviders.presetHints`. */
export type PresetHintKey =
  | "keycloak"
  | "authentik"
  | "authelia"
  | "pocketId"
  | "salesforce"
  | "dex"
  | "custom";

/** A blank in an issuer template, asked for as its own field. */
export interface PresetBlank {
  /** The `{name}` it fills in. */
  name: string;
  /** Which label under `settings:authProviders.blanks` names this field. */
  labelKey: BlankLabelKey;
  /** Shown greyed in the field. Not translated: it is an example address. */
  example: string;
}

export interface ProviderPreset {
  /** Stable id. `icon` is set from this, so it outlives the label. */
  key: string;
  /** What it is called. A product name, so not translated. */
  name: string;
  /** The slug a new provider starts with. Editable, and fixed once saved. */
  slug: string;
  /**
   * The issuer, with `{blank}` for anything the deployment supplies. An empty
   * template means the address is typed in full.
   */
  template: string;
  blanks: PresetBlank[];
  /** Where there is something worth saying beyond the address. */
  hintKey?: PresetHintKey;
}

/** Offered in the order somebody scanning the grid would want them: the
 *  enterprise platforms an organisation already has, then the ones a
 *  deployment runs itself.
 *
 *  Dedicated identity providers only. A self-hosted app that happens to speak
 *  OpenID Connect — a git forge, a chat server — is reached through the
 *  generic entry at the end rather than named here, which is what keeps this
 *  list to things somebody chose as their way in. */
export const PROVIDER_PRESETS: ProviderPreset[] = [
  {
    key: "google",
    name: "Google",
    slug: "google",
    template: "https://accounts.google.com",
    blanks: [],
  },
  {
    key: "microsoft",
    name: "Microsoft Entra ID",
    slug: "microsoft",
    template: "https://login.microsoftonline.com/{tenant}/v2.0",
    blanks: [
      {
        name: "tenant",
        labelKey: "tenant",
        example: "00000000-0000-0000-0000-000000000000",
      },
    ],
  },
  {
    key: "okta",
    name: "Okta",
    slug: "okta",
    template: "https://{host}",
    blanks: [{ name: "host", labelKey: "oktaHost", example: "dev-12345.okta.com" }],
  },
  {
    key: "auth0",
    name: "Auth0",
    slug: "auth0",
    template: "https://{host}",
    blanks: [{ name: "host", labelKey: "auth0Host", example: "your-tenant.eu.auth0.com" }],
  },
  {
    key: "salesforce",
    name: "Salesforce",
    slug: "salesforce",
    template: "https://{host}",
    blanks: [{ name: "host", labelKey: "host", example: "login.salesforce.com" }],
    hintKey: "salesforce",
  },
  {
    key: "jumpcloud",
    name: "JumpCloud",
    slug: "jumpcloud",
    // The trailing slash is part of the issuer JumpCloud publishes, and the
    // address has to match it exactly.
    template: "https://oauth.id.jumpcloud.com/",
    blanks: [],
  },
  {
    key: "keycloak",
    name: "Keycloak",
    slug: "keycloak",
    template: "https://{host}/realms/{realm}",
    blanks: [
      { name: "host", labelKey: "host", example: "keycloak.example.com" },
      { name: "realm", labelKey: "realm", example: "main" },
    ],
    hintKey: "keycloak",
  },
  {
    key: "authentik",
    name: "Authentik",
    slug: "authentik",
    template: "https://{host}/application/o/{application}/",
    blanks: [
      { name: "host", labelKey: "host", example: "authentik.example.com" },
      { name: "application", labelKey: "application", example: "initiative" },
    ],
    hintKey: "authentik",
  },
  {
    key: "authelia",
    name: "Authelia",
    slug: "authelia",
    template: "https://{host}",
    blanks: [{ name: "host", labelKey: "host", example: "auth.example.com" }],
    hintKey: "authelia",
  },
  {
    key: "pocket-id",
    name: "Pocket ID",
    slug: "pocket-id",
    template: "https://{host}",
    blanks: [{ name: "host", labelKey: "host", example: "id.example.com" }],
    hintKey: "pocketId",
  },
  {
    key: "dex",
    name: "Dex",
    slug: "dex",
    // Dex is mounted under a path far more often than at a root, and `/dex`
    // is the convention its own examples use. Whatever the deployment set as
    // its `issuer` is the answer, which is what the hint says.
    template: "https://{host}/dex",
    blanks: [{ name: "host", labelKey: "host", example: "auth.example.com" }],
    hintKey: "dex",
  },
  {
    key: "zitadel",
    name: "Zitadel",
    slug: "zitadel",
    template: "https://{host}",
    blanks: [{ name: "host", labelKey: "host", example: "your-instance.zitadel.cloud" }],
  },
  {
    key: "custom",
    name: "OpenID Connect",
    slug: "",
    template: "",
    blanks: [],
    hintKey: "custom",
  },
];

export const presetFor = (key: string): ProviderPreset =>
  PROVIDER_PRESETS.find((preset) => preset.key === key) ??
  PROVIDER_PRESETS[PROVIDER_PRESETS.length - 1];

/** Whether the address is built from blanks or typed in full. */
export const isCustomPreset = (preset: ProviderPreset) => preset.template === "";

/**
 * The issuer a preset's answers add up to.
 *
 * A blank nobody has filled in is left as its `{name}`, so the field shows
 * what is still missing rather than an address with a hole in it.
 */
export const buildIssuer = (preset: ProviderPreset, answers: Record<string, string>): string =>
  preset.blanks.reduce(
    (url, blank) =>
      url.replace(`{${blank.name}}`, answers[blank.name]?.trim() || `{${blank.name}}`),
    preset.template
  );

/** Whether every blank has an answer, so the address is worth looking up. */
export const issuerIsComplete = (
  preset: ProviderPreset,
  answers: Record<string, string>
): boolean => preset.blanks.every((blank) => Boolean(answers[blank.name]?.trim()));

/** The scopes to start from: what the provider offers, narrowed to what a
 *  sign-in here actually uses, and never fewer than the two it needs. */
export const DEFAULT_SCOPES = ["openid", "email", "profile"];
export const OPTIONAL_SCOPES = ["offline_access", "groups"];

export const suggestScopes = (offered: string[]): string => {
  if (offered.length === 0) return DEFAULT_SCOPES.join(" ");
  const wanted = [...DEFAULT_SCOPES, ...OPTIONAL_SCOPES];
  const agreed = wanted.filter((scope) => offered.includes(scope));
  // A provider that lists scopes but not openid is answering some other
  // question; the flow needs it regardless.
  return agreed.includes("openid") ? agreed.join(" ") : ["openid", ...agreed].join(" ");
};

/** Groups live in different places depending on who is asked, and a provider's
 *  own claim list rarely mentions the nested ones. */
export const GROUPS_CLAIM_SUGGESTIONS = ["groups", "roles", "realm_access.roles"];
