/**
 * A notification has to say what happened and go where it happened.
 *
 * The account notices — a moderator renamed you, took your picture down,
 * suspended you — did neither. They fell past every `case` to the generic
 * "You have a new notification", and their destination was dropped because
 * the resolver only honoured a `target_path` that came with a `guild_id`.
 * These notices belong to the person rather than to any community, so the
 * server sends no guild with them.
 */
import { describe, expect, it } from "vitest";

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
      notificationLink(notice("post_published", { guild_id: 7, target_path: "/posts/3" }))
    ).toBe("/c/7/posts/3");
  });

  it("still leads nowhere when the payload names nowhere", () => {
    expect(notificationLink(notice("username_changed", {}))).toBeNull();
  });
});
