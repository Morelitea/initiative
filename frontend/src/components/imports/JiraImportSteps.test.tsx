import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse } from "msw";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { guildHttp } from "@/__tests__/helpers/guildHttp";
import { server } from "@/__tests__/helpers/msw-server";
import { renderWithProviders } from "@/__tests__/helpers/render";

import {
  JiraChooseStep,
  JiraConnectStep,
  JiraFetchingStep,
  JiraReviewSummary,
} from "./JiraImportSteps";

vi.mock("@/lib/chesterToast", () => ({
  toast: { success: vi.fn(), error: vi.fn(), warning: vi.fn() },
}));

function job(overrides: Record<string, unknown> = {}) {
  return {
    id: 77,
    guild_id: 1,
    created_by: 1,
    source: "atlassian",
    params: {},
    status: "queued",
    plan: null,
    result: null,
    error: null,
    expires_at: null,
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
    ...overrides,
  };
}

const CONNECTION = {
  credentials: {
    site_url: "https://acme.atlassian.net",
    email: "me@example.com",
    api_token: "secret",
  },
  projects: [
    { id: "1", key: "ACME", name: "Acme Board", issue_count: 12 },
    { id: "2", key: "OPS", name: "Operations", issue_count: null },
  ],
};

describe("JiraConnectStep", () => {
  it("proves the token and hands back what the site holds", async () => {
    let sent: Record<string, unknown> | null = null;
    server.use(
      guildHttp.post("/imports/atlassian/connect", async ({ request }) => {
        sent = (await request.json()) as Record<string, unknown>;
        return HttpResponse.json(
          {
            site_url: "https://acme.atlassian.net",
            jira: { available: true, projects: CONNECTION.projects },
            confluence: { available: false },
          },
          { status: 201 }
        );
      })
    );
    const onConnected = vi.fn();
    renderWithProviders(<JiraConnectStep onConnected={onConnected} />);

    await userEvent.type(screen.getByLabelText(/site address/i), "acme.atlassian.net/jira");
    await userEvent.type(screen.getByLabelText(/atlassian email/i), "me@example.com");
    await userEvent.type(screen.getByLabelText(/api token/i), "secret");
    await userEvent.click(screen.getByRole("button", { name: /^connect$/i }));

    await waitFor(() => expect(onConnected).toHaveBeenCalled());
    expect(sent).toEqual({
      site_url: "acme.atlassian.net/jira",
      email: "me@example.com",
      api_token: "secret",
    });
    // The site as the server normalised it is what the import will call.
    expect(onConnected.mock.calls[0][0].credentials.site_url).toBe("https://acme.atlassian.net");
    expect(onConnected.mock.calls[0][0].projects).toHaveLength(2);
  });

  it("says so when the site answers but there is no Jira the token can see", async () => {
    server.use(
      guildHttp.post("/imports/atlassian/connect", () =>
        HttpResponse.json(
          { site_url: "https://acme.atlassian.net", jira: { available: false } },
          { status: 201 }
        )
      )
    );
    const onConnected = vi.fn();
    renderWithProviders(<JiraConnectStep onConnected={onConnected} />);
    await userEvent.type(screen.getByLabelText(/site address/i), "acme.atlassian.net");
    await userEvent.type(screen.getByLabelText(/atlassian email/i), "me@example.com");
    await userEvent.type(screen.getByLabelText(/api token/i), "secret");
    await userEvent.click(screen.getByRole("button", { name: /^connect$/i }));

    expect(await screen.findByText(/no Jira there/i)).toBeInTheDocument();
    expect(onConnected).not.toHaveBeenCalled();
  });
});

describe("JiraChooseStep", () => {
  it("starts a job with the ticked projects, the initiative and the options", async () => {
    let sent: Record<string, unknown> | null = null;
    server.use(
      guildHttp.post("/imports/atlassian/jira", async ({ request }) => {
        sent = (await request.json()) as Record<string, unknown>;
        return HttpResponse.json(job(), { status: 202 });
      })
    );
    const onStarted = vi.fn();
    renderWithProviders(
      <JiraChooseStep
        connection={CONNECTION}
        initiatives={[{ id: 4, name: "Engineering" }]}
        onStarted={onStarted}
      />
    );

    // Counted and uncounted projects both read sensibly.
    expect(screen.getByText("12 issues")).toBeInTheDocument();
    expect(screen.getByText(/not counted/i)).toBeInTheDocument();

    const start = screen.getByRole("button", { name: /read these projects/i });
    expect(start).toBeDisabled();

    await userEvent.click(screen.getByLabelText(/Operations/));
    await userEvent.click(screen.getByLabelText(/bring images/i));
    await userEvent.click(start);

    await waitFor(() => expect(onStarted).toHaveBeenCalled());
    expect(sent).toMatchObject({
      site_url: "https://acme.atlassian.net",
      email: "me@example.com",
      api_token: "secret",
      initiative_id: 4,
      project_keys: ["OPS"],
      include_comments: true,
      include_attachments: false,
    });
  });
});

describe("JiraFetchingStep", () => {
  it("shows the fetch climbing, then hands over the staged job", async () => {
    let polls = 0;
    server.use(
      guildHttp.get("/imports/jobs/:jobId", () => {
        polls += 1;
        return polls < 2
          ? HttpResponse.json(
              job({ status: "fetching", plan: { atlassian: { projects: 1, tasks: 30 } } })
            )
          : HttpResponse.json(
              job({ status: "staged", plan: { atlassian: { projects: 2, tasks: 55 } } })
            );
      })
    );
    const onStaged = vi.fn();
    renderWithProviders(<JiraFetchingStep jobId={77} onStaged={onStaged} onStopped={() => {}} />);

    expect(await screen.findByText(/1 projects and 30 tasks/i)).toBeInTheDocument();
    await waitFor(() => expect(onStaged).toHaveBeenCalled(), { timeout: 4000 });
    expect(onStaged.mock.calls[0][0].status).toBe("staged");
  });

  it("explains a failed fetch in words, and lets somebody start over", async () => {
    server.use(
      guildHttp.get("/imports/jobs/:jobId", () =>
        HttpResponse.json(job({ status: "failed", error: "IMPORT_SOURCE_RATE_LIMITED" }))
      )
    );
    const onStopped = vi.fn();
    renderWithProviders(<JiraFetchingStep jobId={77} onStaged={vi.fn()} onStopped={onStopped} />);

    expect(await screen.findByText(/slow down/i)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /start over/i }));
    expect(onStopped).toHaveBeenCalled();
  });
});

describe("JiraReviewSummary", () => {
  beforeEach(() => vi.clearAllMocks());

  it("says what arrives and, as plainly, what does not", () => {
    renderWithProviders(
      <JiraReviewSummary
        job={
          job({
            status: "staged",
            plan: {
              atlassian: {
                projects: 2,
                tasks: 40,
                links: 7,
                links_outside_selection: 2,
                comments: 12,
                comments_restricted: 1,
                images: 3,
                image_bytes: 2_500_000,
                sprints: 4,
                sprint_calendars: 0,
                sprints_skipped: "IMPORT_TOOL_DISABLED",
                properties: [{ name: "Story points", type: "number", issue_count: 18 }],
                dropped_fields: ["Watchers too"],
                unreadable_projects: ["HR"],
              },
            },
          }) as never
        }
        excluded={new Set()}
        onExcludedChange={() => {}}
      />
    );

    expect(screen.getByText(/40 tasks from 2 project/i)).toBeInTheDocument();
    expect(screen.getByText(/7 links between tasks/i)).toBeInTheDocument();
    expect(screen.getByText(/3 images \(2\.4 MB\)/i)).toBeInTheDocument();
    expect(screen.getByText("Story points")).toBeInTheDocument();
    expect(screen.getByText("18 tasks")).toBeInTheDocument();

    expect(screen.getByText(/not coming across/i)).toBeInTheDocument();
    expect(screen.getByText(/can't read: HR/i)).toBeInTheDocument();
    expect(screen.getByText(/2 links to issues you didn't pick/i)).toBeInTheDocument();
    expect(screen.getByText(/1 comment only some people/i)).toBeInTheDocument();
    expect(screen.getByText(/4 sprints:/i)).toBeInTheDocument();
    expect(screen.getByText(/Watchers too/)).toBeInTheDocument();
  });

  it("lets a property be unticked, and ticked again", async () => {
    const onExcludedChange = vi.fn();
    const staged = job({
      status: "staged",
      plan: {
        atlassian: {
          tasks: 3,
          projects: 1,
          properties: [
            { name: "Story points", type: "number", issue_count: 3 },
            { name: "Team", type: "select", issue_count: 1 },
          ],
        },
      },
    }) as never;

    const { rerender } = renderWithProviders(
      <JiraReviewSummary job={staged} excluded={new Set()} onExcludedChange={onExcludedChange} />
    );
    const storyPoints = screen.getByRole("checkbox", { name: /story points/i });
    expect(storyPoints).toBeChecked();
    await userEvent.click(storyPoints);
    expect([...onExcludedChange.mock.calls[0][0]]).toEqual(["Story points"]);

    rerender(
      <JiraReviewSummary
        job={staged}
        excluded={new Set(["Story points"])}
        onExcludedChange={onExcludedChange}
      />
    );
    const unticked = screen.getByRole("checkbox", { name: /story points/i });
    expect(unticked).not.toBeChecked();
    await userEvent.click(unticked);
    expect([...onExcludedChange.mock.calls[1][0]]).toEqual([]);
  });
});
