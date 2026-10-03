/**
 * The one dialog every ticket is filed through.
 *
 * What it must not do is as important as what it does: a report never says
 * where it went, and tells the reporter nothing about what happens next.
 */
import { act, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { AxiosError, type AxiosResponse } from "axios";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { buildUser } from "@/__tests__/factories";
import { renderWithProviders } from "@/__tests__/helpers/render";

const fileMutate = vi.fn();
const fileOptions = vi.hoisted(() => ({
  current: undefined as { onError?: (e: unknown) => void } | undefined,
}));
const contacts = vi.hoisted(() => ({ moderation: null as string | null }));

vi.mock("@/hooks/useTickets", async () => {
  const actual = await vi.importActual<typeof import("@/hooks/useTickets")>("@/hooks/useTickets");
  return {
    ...actual,
    useTicketAvailability: () => ({
      data: {
        moderation: { mode: "form", contact: contacts.moderation },
        support: { mode: "form", contact: null },
      },
    }),
    useFileTicket: (options: { onError?: (e: unknown) => void }) => {
      fileOptions.current = options;
      return { mutate: fileMutate, isPending: false };
    },
  };
});

import { FileTicketDialog, type FileTicketDialogProps } from "./FileTicketDialog";

const report = (props: Partial<FileTicketDialogProps> = {}) =>
  renderWithProviders(
    <FileTicketDialog
      open
      onOpenChange={() => {}}
      ticket={{ stream: "moderation", targetType: "comment", targetId: 42 }}
      guildId={3}
      {...props}
    />,
    { auth: { user: buildUser() } }
  );

const chooseReason = async (user: ReturnType<typeof userEvent.setup>, name: string) => {
  await user.click(screen.getByRole("combobox", { name: "What is wrong?" }));
  await user.click(await screen.findByRole("option", { name }));
};

describe("FileTicketDialog", () => {
  beforeEach(() => {
    fileMutate.mockClear();
    contacts.moderation = null;
  });

  describe("reporting something", () => {
    it("will not send without a reason", () => {
      report();
      expect(screen.getByRole("button", { name: "Send report" })).toBeDisabled();
    });

    it("sends the target, the reason and the community it was reported from", async () => {
      report();
      const user = userEvent.setup();

      await chooseReason(user, "Harassment");
      await user.click(screen.getByRole("button", { name: "Send report" }));

      expect(fileMutate).toHaveBeenCalledWith({
        stream: "moderation",
        target_type: "comment",
        target_id: 42,
        reason: "harassment",
        detail: null,
        guild_id: 3,
      });
    });

    it("carries the reporter's own words", async () => {
      report();
      const user = userEvent.setup();

      await user.type(screen.getByLabelText("Anything else?"), "  This is abusive.  ");
      await chooseReason(user, "Hate");
      await user.click(screen.getByRole("button", { name: "Send report" }));

      expect(fileMutate).toHaveBeenCalledWith(
        expect.objectContaining({ detail: "This is abusive.", reason: "hate" })
      );
    });

    it("sends no community when the reporter is not in one", async () => {
      report({
        ticket: { stream: "moderation", targetType: "user_profile", targetId: 7 },
        guildId: null,
      });
      const user = userEvent.setup();

      await chooseReason(user, "Spam");
      await user.click(screen.getByRole("button", { name: "Send report" }));

      expect(fileMutate).toHaveBeenCalledWith(
        expect.objectContaining({ target_type: "user_profile", guild_id: null })
      );
    });

    it("never says where the report will go", () => {
      report();
      // Nothing in the dialog names a venue, a project or a moderator: where
      // it goes is decided server-side and is not the reporter's business.
      for (const leak of [/moderator/i, /platform/i, /operations/i, /initiative/i]) {
        expect(screen.queryByText(leak)).not.toBeInTheDocument();
      }
    });

    it("offers the deployment's address when nothing could receive the report", async () => {
      contacts.moderation = "trust@example.org";
      report();

      act(() => {
        fileOptions.current?.onError?.(
          new AxiosError("unavailable", "ERR_BAD_RESPONSE", undefined, undefined, {
            status: 503,
          } as AxiosResponse)
        );
      });

      expect(await screen.findByText("trust@example.org")).toBeInTheDocument();
    });
  });

  describe("asking for help", () => {
    it("sends the subject and words, trimmed, from the community", async () => {
      renderWithProviders(
        <FileTicketDialog
          open
          onOpenChange={() => {}}
          ticket={{ stream: "support" }}
          guildId={3}
        />,
        { auth: { user: buildUser() } }
      );
      const user = userEvent.setup();

      const send = screen.getByRole("button", { name: "Send" });
      expect(send).toBeDisabled();
      await user.type(screen.getByLabelText("What is this about?"), " Lost my phone ");
      await user.type(screen.getByLabelText("What happened?"), "I can't sign in.");
      await user.click(send);

      expect(fileMutate).toHaveBeenCalledWith({
        stream: "support",
        guild_id: 3,
        subject: "Lost my phone",
        body: "I can't sign in.",
      });
    });
  });
});
