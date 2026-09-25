import { useRouter } from "@tanstack/react-router";
import { useCallback, useEffect, useRef } from "react";

import { useAuth } from "@/hooks/useAuth";
import { useGuilds } from "@/hooks/useGuilds";
import { guildIdFromPath } from "@/lib/guildUrl";
import { returnPath } from "@/lib/returnPath";

/** Takes somebody who has just signed in to the page they were headed for. */
export type ResumeAfterSignIn = (next: string | null | undefined) => Promise<void>;

/**
 * Where a finished sign-in lands, for every page that finishes one.
 *
 * A sign-in that interrupted something carries the interrupted address as
 * `next`. It is read through `returnPath`, so only a path in this app is kept,
 * and anything else starts them at home.
 *
 * `next` is carried by a browser rather than by an account: the session that
 * expired, or the one a step-up ended, may not be the account now signing in.
 * A path inside a community is only theirs to resume if that community is in
 * their list, so the list is asked for before going there, and they start at
 * home if it is not.
 */
export const useResumeAfterSignIn = (): ResumeAfterSignIn => {
  const router = useRouter();
  const { user } = useAuth();
  const { refreshGuilds } = useGuilds();

  // A sign-in resolves before the providers have re-rendered with its account,
  // so the caller's closure still holds the list reader of whoever was here
  // before. The latest one is read at call time instead, and a caller that got
  // ahead of the account waits for it to arrive.
  const refreshGuildsRef = useRef(refreshGuilds);
  refreshGuildsRef.current = refreshGuilds;
  const signedInRef = useRef(Boolean(user));
  signedInRef.current = Boolean(user);
  const waitersRef = useRef<Array<() => void>>([]);

  useEffect(() => {
    if (!user || waitersRef.current.length === 0) return;
    const waiting = waitersRef.current;
    waitersRef.current = [];
    for (const resolve of waiting) resolve();
  }, [user]);

  const untilSignedIn = useCallback((): Promise<void> => {
    if (signedInRef.current) return Promise.resolve();
    return new Promise((resolve) => {
      waitersRef.current.push(resolve);
    });
  }, []);

  return useCallback(
    async (next) => {
      const returnTo = returnPath(next) ?? "/";
      const wanted = guildIdFromPath(returnTo);
      if (wanted === null) {
        router.navigate({ to: returnTo, replace: true });
        return;
      }
      await untilSignedIn();
      const reachable = await refreshGuildsRef.current();
      router.navigate({
        to: reachable.some((guild) => guild.id === wanted) ? returnTo : "/",
        replace: true,
      });
    },
    [router, untilSignedIn]
  );
};
