/**
 * The team's side of a case: who filed it, and a way to answer them that
 * reaches only them.
 */
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { buildComment, buildUser } from "@/__tests__/factories";
import { renderWithProviders } from "@/__tests__/helpers/render";
import type { TaskCaseRead } from "@/api/generated/initiativeAPI.schemas";

const state = vi.hoisted(() => ({ found: undefined as TaskCaseRead | undefined }));
const createComment = vi.fn();
const updateTask = vi.fn();

vi.mock("@/hooks/useTickets", async () => {
  const actual = await vi.importActual<typeof import("@/hooks/useTickets")>("@/hooks/useTickets");
  return { ...actual, useTaskCase: () => ({ data: state.found }), refreshTaskCase: vi.fn() };
});
vi.mock("@/hooks/useComments", async () => {
  const actual = await vi.importActual<typeof import("@/hooks/useComments")>("@/hooks/useComments");
  return { ...actual, useCreateComment: () => ({ mutateAsync: createComment, isPending: false }) };
});
vi.mock("@/hooks/useTasks", async () => {
  const actual = await vi.importActual<typeof import("@/hooks/useTasks")>("@/hooks/useTasks");
  return { ...actual, useUpdateTask: () => ({ mutateAsync: updateTask, isPending: false }) };
});

// The name links to a profile, which needs a router this test does not mount.
vi.mock("@/components/user/UserHoverLink", () => ({
  UserHoverLink: ({ children }: { children: React.ReactNode }) => <span>{children}</span>,
}));

import { CasePanel } from "./CasePanel";

const filer = buildUser({ id: 40, username: "asker" });
const supportCase = (overrides: Partial<TaskCaseRead> = {}): TaskCaseRead => ({
  stream: "support",
  opened_at: new Date().toISOString(),
  filer: { ...filer, display_name: null } as TaskCaseRead["filer"],
  filer_subject: "Lost my phone",
  conversation: "open",
  awaiting_filer_status_id: 9,
  active_status_id: 8,
  ...overrides,
});

const renderPanel = () =>
  renderWithProviders(<CasePanel taskId={3} canEdit />, { auth: { user: buildUser() } });

describe("CasePanel", () => {
  beforeEach(() => {
    state.found = undefined;
    createComment.mockReset().mockResolvedValue(buildComment({ id: 1 }));
    updateTask.mockReset().mockResolvedValue({});
  });

  it("renders nothing for a task no stream opened", () => {
    const { container } = renderPanel();
    expect(container).toBeEmptyDOMElement();
  });

  it("shows who filed it and what they called it", async () => {
    state.found = supportCase();
    renderPanel();
    expect(await screen.findByText("Lost my phone")).toBeInTheDocument();
    expect(screen.getByText(/asker/)).toBeInTheDocument();
  });

  it("says a reply to them is said to them", async () => {
    state.found = supportCase();
    const user = userEvent.setup();
    renderPanel();
    await user.type(screen.getByRole("textbox"), "Try a recovery code.");
    await user.click(screen.getByRole("button", { name: "Send reply" }));
    expect(createComment).toHaveBeenCalledWith({
      content: "Try a recovery code.",
      task_id: 3,
      audience: "filer",
    });
    expect(updateTask).not.toHaveBeenCalled();
  });

  it("moves the case to waiting on them when asked to", async () => {
    state.found = supportCase();
    const user = userEvent.setup();
    renderPanel();
    await user.type(screen.getByRole("textbox"), "Which phone?");
    await user.click(screen.getByRole("button", { name: "Send and wait for them" }));
    expect(updateTask).toHaveBeenCalledWith({ taskId: 3, data: { task_status_id: 9 } });
  });

  it("offers no waiting where the stream names no waiting status", () => {
    state.found = supportCase({ awaiting_filer_status_id: null });
    renderPanel();
    expect(screen.queryByRole("button", { name: "Send and wait for them" })).toBeNull();
  });

  it("offers no reply where the stream holds no conversation", () => {
    state.found = supportCase({ stream: "moderation", conversation: "none" });
    renderPanel();
    expect(screen.queryByRole("textbox")).toBeNull();
  });

  it("shows the conversation with the requester, apart from the thread", async () => {
    const now = new Date().toISOString();
    state.found = supportCase({
      messages: [
        {
          id: 1,
          author: { ...filer, display_name: null } as TaskCaseRead["filer"],
          from_requester: true,
          content: "Where are my tasks?",
          created_at: now,
        },
        {
          id: 2,
          author: {
            ...buildUser({ username: "helper" }),
            display_name: null,
          } as TaskCaseRead["filer"],
          from_requester: false,
          content: "Try My Tasks.",
          created_at: now,
        },
      ],
    });
    renderPanel();
    const conversation = await screen.findByRole("list", { name: /Conversation with/ });
    expect(conversation).toHaveTextContent("Where are my tasks?");
    expect(conversation).toHaveTextContent("Try My Tasks.");
    expect(conversation).toHaveTextContent(/The team \(helper/);
  });

  it("lets the requester answer feedback only once the team has written", async () => {
    state.found = supportCase({ stream: "feedback", conversation: "staff_first", messages: [] });
    renderPanel();
    expect(await screen.findByText(/once the team has said something/)).toBeInTheDocument();
  });
});
