/**
 * A notification has to say what happened and go where it happened.
 *
 * The account notices — a moderator renamed you, took your picture down,
 * suspended you — did neither. They fell past every `case` to the generic
 * "You have a new notification", and their destination was dropped because
 * the resolver only honoured a `target_path` that came with a `community_id`.
 * These notices belong to the person rather than to any community, so the
 * server sends no guild with them.
 */
import { Capacitor } from "@capacitor/core";
import { describe, expect, it, vi } from "vitest";

import { buildNotification } from "@/__tests__/factories/notification.factory";
import type { NotificationType } from "@/api/generated/initiativeAPI.schemas";

import { notificationLink, notificationText } from "./notificationLine";

// The real strings are asserted through i18n keys rather than English, so a
// reworded translation doesn't fail this; what matters is that a key was
// resolved at all instead of the fallback.
const t = (key: string, options?: Record<string, unknown>) =>
  options && Object.keys(options).length ? `${key}(${JSON.stringify(options)})` : key;

const notice = (type: string, data: Record<string, unknown>) =>
  buildNotification({ type: type as NotificationType, data });

describe("notificationText — account notices", () => {
  it("says which handle a moderator took away", () => {
    const line = notificationText(
      notice("username_changed", {
        previous_handle: "oldname#1234",
        target_path: "/settings/profile",
      }),
      t
    );

    expect(line).toContain("notifications.usernameChanged");
    expect(line).toContain("oldname#1234");
    expect(line).not.toContain("defaultNotification");
  });

  it("still reads as a sentence when the old handle wasn't recorded", () => {
    const line = notificationText(notice("username_changed", {}), t);

    expect(line).toContain("notifications.usernameChanged");
    expect(line).toContain("notifications.yourPreviousHandle");
  });

  it("gives the reason for a suspension when there is one", () => {
    expect(notificationText(notice("account_suspended", { reason: "spam" }), t)).toContain(
      "notifications.accountSuspendedWithReason"
    );
    // A reason that is only whitespace is no reason at all.
    expect(notificationText(notice("account_suspended", { reason: "   " }), t)).toBe(
      "notifications.accountSuspended"
    );
    expect(notificationText(notice("account_suspended", { reason: null }), t)).toBe(
      "notifications.accountSuspended"
    );
  });

  it("names who to contact about a hold when there is somebody", () => {
    const named = notice("community_on_hold", { community: "Acme", contact: "help@example.com" });
    const nobody = notice("community_on_hold", { community: "Acme", contact: null });
    expect(notificationText(named, t)).toContain("notifications.guildOnHoldWithContact");
    expect(notificationText(nobody, t)).toContain("notifications.guildOnHold");
    expect(notificationText(nobody, t)).not.toContain("WithContact");
  });

  it("names the day a held community is deleted, where it is", () => {
    const dated = notice("community_on_hold", {
      community: "Acme",
      contact: "help@example.com",
      delete_on: "2026-10-24",
    });
    const line = notificationText(dated, t);
    expect(line).toContain("notifications.guildOnHoldDeletingWithContact");
    expect(line).toContain("2026");
    expect(
      notificationText(
        notice("community_on_hold", { community: "Acme", delete_on: "2026-10-24" }),
        t
      )
    ).toContain("notifications.guildOnHoldDeleting(");
  });

  it("says when a trial ends, that it has, and that a new community is ready", () => {
    const ending = notificationText(
      notice("community_trial_ending", { community: "Acme", trial_ends_on: "2026-10-08" }),
      t
    );
    expect(ending).toContain("notifications.guildTrialEnding");
    expect(ending).toContain("Acme");
    expect(ending).toContain("2026");
    expect(notificationText(notice("community_trial_ended", { community: "Acme" }), t)).toContain(
      "notifications.guildTrialEnded"
    );
    expect(notificationText(notice("community_welcome", { community: "Acme" }), t)).toBe(
      'notifications.guildWelcome({"community":"Acme"})'
    );
  });

  it("asks for no plan in the phone app, which may not sell", () => {
    const native = vi.spyOn(Capacitor, "isNativePlatform").mockReturnValue(true);
    try {
      expect(
        notificationText(
          notice("community_trial_ending", { community: "Acme", trial_ends_on: "2026-10-08" }),
          t
        )
      ).toContain("notifications.guildTrialEndingInApp(");
      expect(notificationText(notice("community_trial_ended", { community: "Acme" }), t)).toBe(
        'notifications.guildTrialEndedInApp({"community":"Acme"})'
      );
      expect(notificationText(notice("community_welcome", { community: "Acme" }), t)).toBe(
        'notifications.guildWelcomeInApp({"community":"Acme"})'
      );
    } finally {
      native.mockRestore();
    }
  });

  it("takes a trial notice to the community's Plan & usage tab", () => {
    expect(
      notificationLink(
        notice("community_trial_ending", { community_id: 7, target_path: "/settings/usage" })
      )
    ).toBe("/c/7/settings/usage");
  });

  it("covers the rest of the account notices", () => {
    expect(notificationText(notice("avatar_removed", {}), t)).toBe("notifications.avatarRemoved");
    expect(notificationText(notice("account_unsuspended", {}), t)).toBe(
      "notifications.accountUnsuspended"
    );
  });
});

describe("notificationLink — a target_path without a guild", () => {
  it("takes an account notice to the account screen", () => {
    expect(notificationLink(notice("username_changed", { target_path: "/profile/account" }))).toBe(
      "/profile/account"
    );
    expect(notificationLink(notice("avatar_removed", { target_path: "/profile" }))).toBe(
      "/profile"
    );
  });

  it("rewrites the route that never existed", () => {
    // Rows already written carry `/settings/profile`, which is not a page.
    // The server stopped minting it; these are the ones already sent.
    expect(notificationLink(notice("username_changed", { target_path: "/settings/profile" }))).toBe(
      "/profile/account"
    );
  });

  it("keeps scoping a path that does name a guild", () => {
    expect(
      notificationLink(notice("post_published", { community_id: 7, target_path: "/posts/3" }))
    ).toBe("/c/7/posts/3");
  });

  it("still leads nowhere when the payload names nowhere", () => {
    expect(notificationLink(notice("username_changed", {}))).toBeNull();
  });
});

describe("notificationText — mentions", () => {
  it("names the task whose description mentioned you", () => {
    const line = notificationText(
      notice("mention", { task_id: 7, task_title: "Ship it", mentioned_by_name: "ada" }),
      t
    );

    expect(line).toContain("notifications.mentionTaskDescription");
    expect(line).toContain("Ship it");
  });

  it("still reads a mention in a comment on a task as a comment mention", () => {
    const line = notificationText(
      notice("mention", { task_id: 7, comment_id: 3, context_title: "Ship it" }),
      t
    );

    expect(line).toContain("notifications.mentionComment");
  });
});

describe("an app asking to act as the reader", () => {
  const request = notice("app_consent_requested", {
    community_id: 4,
    app_id: 7,
    app_name: "Auto",
    label: "Comment on the linked issue",
    target_path: "/?app=7",
  });

  it("names the app and quotes what it asked", () => {
    expect(notificationText(request, t)).toBe(
      `notifications.appConsentRequested(${JSON.stringify({
        app: "Auto",
        label: "Comment on the linked issue",
      })})`
    );
  });

  it("opens that app's settings in its community", () => {
    expect(notificationLink(request)).toBe("/c/4/?app=7");
  });
});

describe("an app version waiting for the seat", () => {
  const waiting = notice("app_update_pending", {
    community_id: 4,
    app_id: 7,
    app_name: "Auto",
    version: "1.2.0",
    target_path: "/settings/integrations",
  });

  it("names the app and the version", () => {
    expect(notificationText(waiting, t)).toBe(
      `notifications.appUpdatePending(${JSON.stringify({ app: "Auto", version: "1.2.0" })})`
    );
  });

  it("opens the community's integrations settings", () => {
    expect(notificationLink(waiting)).toBe("/c/4/settings/integrations");
  });
});
