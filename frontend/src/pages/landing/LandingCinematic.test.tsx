import { screen, waitFor, within } from "@testing-library/react";
import { HttpResponse, http } from "msw";
import { beforeEach, describe, expect, it } from "vitest";

import { server } from "@/__tests__/helpers/msw-server";
import { renderPage } from "@/__tests__/helpers/render";
import { catalogUrl, portalPricingUrl } from "@/hooks/useBillingCatalog";
import { androidApkUrl, docsUrl } from "@/lib/links";
import { TOOLS, toolCamelPlural } from "@/lib/tools";

import landing from "../../../public/locales/en/landing.json";
import { LandingCinematic } from "./LandingCinematic";

const PORTAL = "https://billing.example.com";
const NATIVE_FLOOR = "0.69.0";

/** A price book in the shape the portal serves. Names and numbers are
 *  invented here, because none of them live in this repository. */
const CATALOG = {
  catalog_version: 1,
  updated: "2026-01-01",
  currency: "USD",
  headline: "Where the club keeps its act together",
  subhead: "One community per group, all from the same login.",
  tiers: [
    {
      id: "self_hosted",
      name: "Self-Hosted",
      kind: "free_self_hosted",
      tagline: "Free, because you're the one running it",
      audience: "For the person who'd rather run it themselves.",
      highlight: false,
      badge: null,
      price: { base_monthly: 0, display: "Free", sub_display: "you host it" },
      limits: { storage_display: "Your disks", automations_display: null },
      support: "Peer support",
      features: [],
      feature_keys: [],
      cta: { kind: "external", label: "Read the self-host guide", note: null },
    },
    {
      id: "pewter",
      name: "Pewter",
      kind: "free_hosted",
      tagline: "For one person",
      audience: "For one person and their own week.",
      highlight: false,
      badge: "One free community per person",
      price: { base_monthly: 0, display: "Free", sub_display: "forever, and no card" },
      limits: {
        storage_display: "100 MB",
        automations_display: "No automations",
        members_display: "Just you",
      },
      support: "Peer support",
      features: [],
      feature_keys: [],
      cta: { kind: "signup", label: "Make your free community", note: "No card." },
    },
    {
      id: "brass",
      name: "Brass",
      kind: "paid",
      tagline: "For getting a group moving",
      audience: "For clubs and committees.",
      highlight: true,
      badge: "Most groups land here",
      price: { base_monthly: 7, display: "$7", sub_display: "per month" },
      limits: { storage_display: "5 GB", automations_display: "500 runs/mo" },
      support: "Email support",
      features: [],
      feature_keys: [],
      cta: { kind: "checkout", label: "Choose Brass", note: null },
    },
  ],
  features: {},
  footnotes: {},
};

const stubConfig = (billing: { url: string } | null) =>
  http.get("/api/v1/config", () =>
    HttpResponse.json({
      captcha: null,
      billing: billing ? { ...billing, operator_handoff: false } : null,
      max_upload_bytes: 1024,
      community_directory_enabled: false,
      community_age_gate_enabled: true,
      login_methods: ["password"],
      min_native_version: NATIVE_FLOOR,
    })
  );

const stubBootstrap = (publicRegistrationEnabled: boolean) =>
  http.get("/api/v1/auth/bootstrap", () =>
    HttpResponse.json({ has_users: true, public_registration_enabled: publicRegistrationEnabled })
  );

const stubCatalog = (body: unknown = CATALOG, status = 200) =>
  http.get(catalogUrl(PORTAL), () => HttpResponse.json(body, { status }));

/** Nobody signed in: the page's whole audience. */
const signedOut = { auth: { token: null, user: null, loading: false } };

const renderLanding = () => renderPage(LandingCinematic, signedOut);

describe("LandingCinematic", () => {
  beforeEach(() => {
    server.use(stubConfig(null), stubBootstrap(true));
  });

  it("leads with signing in, and offers to start a community when registration is open", async () => {
    renderLanding();

    expect(
      await screen.findByRole("heading", { level: 1, name: landing.hero.titleAria })
    ).toBeInTheDocument();
    expect(screen.getByText(landing.hero.invited)).toBeInTheDocument();
    const signIn = screen.getAllByRole("link", { name: landing.hero.ctaSignIn });
    expect(signIn.length).toBeGreaterThan(0);
    expect(signIn[0]).toHaveAttribute("href", "/login");

    await waitFor(() => {
      expect(screen.getAllByRole("link", { name: landing.hero.ctaStart })[0]).toHaveAttribute(
        "href",
        "/register"
      );
    });
  });

  it("hides every way to start a community when registration is closed", async () => {
    server.use(stubBootstrap(false));
    renderLanding();

    // The bootstrap answer arrives asynchronously; the buttons leave with it.
    await waitFor(() => {
      expect(screen.queryByRole("link", { name: landing.hero.ctaStart })).not.toBeInTheDocument();
    });
    expect(screen.getAllByRole("link", { name: landing.hero.ctaSignIn }).length).toBeGreaterThan(0);
  });

  it("sends somebody already signed in to their tasks", async () => {
    const { router } = renderPage(LandingCinematic, {
      auth: { token: "test-token", loading: false },
    });

    await waitFor(() => {
      expect(router.state.location.pathname).toBe("/tasks");
    });
  });

  it("draws one card per tool in the registry, named as the sidebar names it", async () => {
    renderLanding();

    await waitFor(() => {
      expect(document.querySelectorAll("[data-tool]")).toHaveLength(TOOLS.length);
    });
    for (const tool of TOOLS) {
      expect(document.querySelector(`[data-tool="${tool}"]`)).not.toBeNull();
    }
  });

  it("links the help center pages", async () => {
    renderLanding();

    // A help card's accessible name is its title followed by its blurb.
    expect(
      await screen.findByRole("link", { name: new RegExp(`^${landing.docs.faqTitle}`) })
    ).toHaveAttribute("href", docsUrl("faq/"));
    expect(screen.getByRole("link", { name: landing.invited.cta })).toHaveAttribute(
      "href",
      docsUrl("getting-started/a-quick-tour/")
    );
  });

  describe("plans", () => {
    it("shows no plans on a deployment without a billing portal", async () => {
      renderLanding();

      // Let the config answer land before asserting the section stayed away.
      await screen.findByTestId("android-apk");
      expect(document.querySelector("#pricing")).toBeNull();
      expect(screen.queryByText(CATALOG.headline)).not.toBeInTheDocument();
    });

    it("renders the portal's catalog, in its words, with each plan's button going somewhere", async () => {
      server.use(stubConfig({ url: PORTAL }), stubCatalog());
      renderLanding();

      expect(await screen.findByText(CATALOG.headline)).toBeInTheDocument();
      const plans = screen.getByRole("list", { name: landing.pricing.tierListAria });
      expect(plans.querySelectorAll("[data-tier]")).toHaveLength(CATALOG.tiers.length);

      expect(within(plans).getByText("$7")).toBeInTheDocument();
      expect(within(plans).getByText("Most groups land here")).toBeInTheDocument();
      expect(within(plans).getByText("Just you")).toBeInTheDocument();

      // Signing up is this app's own door; buying goes to the portal; running
      // it yourself goes to the install guide.
      expect(within(plans).getByRole("link", { name: "Make your free community" })).toHaveAttribute(
        "href",
        "/register"
      );
      expect(within(plans).getByRole("link", { name: /Choose Brass/ })).toHaveAttribute(
        "href",
        portalPricingUrl(PORTAL)
      );
      expect(within(plans).getByRole("link", { name: /Read the self-host guide/ })).toHaveAttribute(
        "href",
        docsUrl("admin/installation/")
      );
      expect(
        screen.getByRole("link", { name: new RegExp(landing.pricing.seeAll) })
      ).toHaveAttribute("href", portalPricingUrl(PORTAL));
    });

    it("sends a free plan's sign-up to the login page when registration is closed", async () => {
      server.use(stubConfig({ url: PORTAL }), stubCatalog(), stubBootstrap(false));
      renderLanding();

      const plans = await screen.findByRole("list", { name: landing.pricing.tierListAria });
      await waitFor(() => {
        expect(
          within(plans).getByRole("link", { name: "Make your free community" })
        ).toHaveAttribute("href", "/login");
      });
    });

    it("leaves the section out when the portal cannot be reached", async () => {
      server.use(stubConfig({ url: PORTAL }), stubCatalog({ detail: "down" }, 503));
      renderLanding();

      // The section exists while the catalog is in flight, then goes.
      await waitFor(() => {
        expect(document.querySelector("#pricing")).not.toBeNull();
      });
      await waitFor(() => {
        expect(document.querySelector("#pricing")).toBeNull();
      });
    });

    it("leaves the section out when the portal answers with something else", async () => {
      server.use(stubConfig({ url: PORTAL }), stubCatalog({ hello: "world" }));
      renderLanding();

      await waitFor(() => {
        expect(document.querySelector("#pricing")).not.toBeNull();
      });
      await waitFor(() => {
        expect(document.querySelector("#pricing")).toBeNull();
      });
    });
  });

  describe("get the app", () => {
    it("offers the Android app from the release this server's floor names", async () => {
      renderLanding();

      const apk = await screen.findByTestId("android-apk");
      expect(apk).toHaveAttribute("href", androidApkUrl(NATIVE_FLOOR));
      expect(apk).toHaveAttribute("download");
    });

    it("puts the visitor's own platform first", async () => {
      renderLanding();

      // jsdom is not a phone.
      await waitFor(() => {
        expect(document.querySelectorAll("[data-platform]")).toHaveLength(3);
      });
      const cards = document.querySelectorAll("[data-platform]");
      expect(cards[0]).toHaveAttribute("data-platform", "desktop");
      expect(cards[0]).toHaveAttribute("data-detected", "true");
      expect(cards[1]).not.toHaveAttribute("data-detected");
    });
  });
});

describe("landing copy covers the tool registry", () => {
  it("has a blurb for every tool, keyed by its camel plural", () => {
    const blurbs = landing.tools as Record<string, string>;
    for (const tool of TOOLS) {
      const key = toolCamelPlural(tool);
      expect(blurbs[key], `landing.json tools.${key}`).toBeTypeOf("string");
    }
  });
});
