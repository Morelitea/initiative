/**
 * The start flow, signed out: which paths a deployment offers, and what the
 * account it ends in is sent with.
 */
import { createMemoryHistory, createRouter } from "@tanstack/react-router";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse, http } from "msw";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { buildUser } from "@/__tests__/factories";
import { server } from "@/__tests__/helpers/msw-server";
import { buildRouterContext, renderPage } from "@/__tests__/helpers/render";
import { catalogUrl } from "@/hooks/useBillingCatalog";
import { clearStart } from "@/lib/startFlow";
import { routeTree } from "@/routeTree.gen";

import { StartPage } from "./StartPage";

const PORTAL = "https://billing.example.test";

const deployment = {
  registrationOpen: true,
  directory: true,
  billing: false,
};

const stubDeployment = () =>
  server.use(
    http.get("/api/v1/config", () =>
      HttpResponse.json({
        captcha: null,
        billing: deployment.billing ? { url: PORTAL, operator_handoff: false } : null,
        max_upload_bytes: 1024,
        community_directory_enabled: deployment.directory,
        community_age_gate_enabled: true,
        login_methods: ["password"],
      })
    ),
    http.get("/api/v1/auth/bootstrap", () =>
      HttpResponse.json({
        has_users: true,
        public_registration_enabled: deployment.registrationOpen,
      })
    ),
    http.get("/api/v1/auth/username-available", () => HttpResponse.json({ available: true })),
    http.get(catalogUrl(PORTAL), () =>
      HttpResponse.json({
        catalog_version: 1,
        currency: "USD",
        headline: "Plans",
        subhead: "",
        footnotes: {},
        tiers: ["free_hosted", "paid"].map((kind) => ({
          id: kind,
          name: kind === "paid" ? "Brass" : "Seedling",
          kind,
          tagline: "",
          audience: "",
          highlight: false,
          badge: null,
          price: { base_monthly: null, display: kind === "paid" ? "$7" : "$0", sub_display: null },
          limits: {},
          support: "",
          features: [],
          cta: { kind: "signup", label: "Start", note: null },
        })),
      })
    )
  );

const register = vi.fn();

const renderStart = (options: { inviteCode?: string; native?: boolean } = {}) =>
  renderPage(StartPage, {
    initialRoute: "/start",
    routerSearch: options.inviteCode ? { invite_code: options.inviteCode } : undefined,
    auth: { user: null, token: null, register },
    server: { isNativePlatform: options.native ?? false },
  });

const heading = (name: string | RegExp) => screen.findByRole("heading", { name });
const press = (name: string | RegExp) => userEvent.click(screen.getByRole("button", { name }));

/** Reach the date through the app's picker: open it, type the date, commit. */
const enterBirthdate = async (date: string) => {
  await userEvent.click(await screen.findByLabelText("Date of birth"));
  await userEvent.type(await screen.findByLabelText("Type or pick a date"), `${date}{Enter}`);
  await userEvent.keyboard("{Escape}");
};

const createAccount = async () => {
  await heading("Create your account");
  await userEvent.type(screen.getByLabelText("Email"), "new@example.com");
  await userEvent.type(screen.getByLabelText(/username/i), "newbie");
  await userEvent.type(screen.getByLabelText(/^password/i), "a-long-enough-password");
  await userEvent.type(screen.getByLabelText(/confirm password/i), "a-long-enough-password");
  await press("Sign up");
  await heading("Check your email");
};

beforeEach(async () => {
  Object.assign(deployment, { registrationOpen: true, directory: true, billing: false });
  stubDeployment();
  await clearStart();
  // Made, but its address is unconfirmed: the flow stops at "check your email".
  register.mockReset().mockResolvedValue(buildUser({ status: "active", email_verified: false }));
});

describe("which paths are offered", () => {
  it("offers only the invite where sign-up without one is closed", async () => {
    deployment.registrationOpen = false;
    renderStart();

    expect(await heading("Invite required")).toBeInTheDocument();
    expect(screen.queryByRole("radio")).not.toBeInTheDocument();
    expect(screen.getByLabelText("Invite code or link")).toBeInTheDocument();
  });

  it.each([
    [true, true],
    [false, false],
  ])("offers joining only where the directory runs (directory %s)", async (directory, shown) => {
    deployment.directory = directory;
    renderStart();

    await heading("What brings you here?");
    expect(Boolean(screen.queryByRole("radio", { name: /join a community/i }))).toBe(shown);
    expect(screen.getByRole("radio", { name: /just for me/i })).toBeChecked();
  });

  it("lets the native app pick a plan, sent with the community rather than the portal", async () => {
    deployment.billing = true;
    const open = vi.spyOn(window, "open");
    renderStart({ native: true });

    await heading("What brings you here?");
    await userEvent.click(screen.getByRole("radio", { name: /for a group/i }));
    await press("Continue");
    await heading("About you");
    await press("Continue");
    await heading("Your community");
    await press("Continue");
    await heading("Choose a plan");
    await press(/Brass/);
    await press("Continue");
    await createAccount();

    expect(register).toHaveBeenCalledWith(
      expect.objectContaining({ community: { name: "My community", plan: "paid" } })
    );
    expect(open).not.toHaveBeenCalled();
    expect(screen.getByText("We'll email you about setting up your plan.")).toBeInTheDocument();
  });
});

describe("what the account is made with", () => {
  it("reaches the account on Continue alone and sends the default community", async () => {
    renderStart();

    await heading("What brings you here?");
    await press("Continue");
    await heading("About you");
    await press("Continue");
    await heading("Your space");
    await press("Continue");
    await createAccount();

    expect(register).toHaveBeenCalledWith(
      expect.objectContaining({ email: "new@example.com", community: { name: "My space" } })
    );
  });

  it("sends the birthdate and no community for joining", async () => {
    renderStart();

    await heading("What brings you here?");
    await userEvent.click(screen.getByRole("radio", { name: /join a community/i }));
    await press("Continue");
    await heading("What are you into?");
    await press("Skip");
    await heading("About you");
    // Joining a listed community needs the answer, so there is no skipping it.
    expect(screen.queryByRole("button", { name: "Skip" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Continue" })).toBeDisabled();
    await enterBirthdate("1990-05-04");
    await press("Continue");
    await createAccount();

    const sent = register.mock.calls[0][0];
    expect(sent).toMatchObject({ birthdate: "1990-05-04" });
    expect(sent.community).toBeUndefined();
    expect(sent.inviteCode).toBeUndefined();
  });
});

it("sends /register to /start with its invite", async () => {
  const router = createRouter({
    routeTree,
    context: buildRouterContext(),
    history: createMemoryHistory({ initialEntries: ["/register?invite_code=abc123"] }),
  });
  await router.load();

  await waitFor(() => expect(router.state.location.pathname).toBe("/start"));
  expect(router.state.location.search).toEqual({ invite_code: "abc123" });
});
