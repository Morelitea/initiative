import { useEffect, useRef } from "react";

import type { CookieConsentRead } from "@/api/generated/initiativeAPI.schemas";
import { setCookieConsentApiV1UsersMeCookieConsentPut } from "@/api/generated/users/users";
import { useAuth } from "@/hooks/useAuth";
import {
  adoptConsent,
  CONSENT_VERSION,
  getConsentState,
  KNOWN_CONSENT_CATEGORIES,
  markConsentSynced,
  type OptionalConsentCategory,
} from "@/lib/consent";

/** The account's answer, where it answered the question we are asking. An
 *  answer to an older version is not an answer to this one, so it is left
 *  alone and the question gets put again. */
const usable = (consent: CookieConsentRead | null | undefined) =>
  consent && consent.version === CONSENT_VERSION ? consent : null;

const asCategories = (granted: readonly string[]): OptionalConsentCategory[] =>
  KNOWN_CONSENT_CATEGORIES.filter((category) => granted.includes(category));

/**
 * Keeps this browser's cookie answer and the account's in step.
 *
 * The browser's copy is the one that governs what loads — it has to be, since
 * somebody reading the landing page has no account and the question is about
 * their browser either way. The account's copy is what saves them answering it
 * again on their phone, and what carries a change of mind back to the laptop.
 *
 * Which one wins is settled without comparing two clocks. An answer given here
 * is marked unsent until the account has it, so:
 *
 * - unsent here → the account is told. This covers answering before signing
 *   in, and it means an answer somebody has just given is never overwritten by
 *   a stale one from elsewhere.
 * - nothing here → the account's is adopted, and this browser never asks.
 * - both, and the account's stamp is not the one this browser sent → it was
 *   answered again somewhere else, so that answer is adopted here too.
 *
 * Signed out, none of this runs and the browser's own copy is all there is.
 */
export const useConsentSync = () => {
  const { user } = useAuth();
  // One reconcile per answer, not one per render: the effect reads state it
  // also writes.
  const settled = useRef<string | null>(null);

  useEffect(() => {
    if (!user) {
      settled.current = null;
      return;
    }

    const local = getConsentState().record;
    const account = usable(user.cookie_consent);
    const seen = `${local?.decidedAt ?? ""}|${local?.syncedAt ?? ""}|${account?.decided_at ?? ""}`;
    if (settled.current === seen) return;
    settled.current = seen;

    if (local === null) {
      if (account) {
        adoptConsent({
          granted: asCategories(account.granted),
          version: account.version,
          decidedAt: account.decided_at,
        });
      }
      return;
    }

    if (local.syncedAt === null || account === null) {
      void setCookieConsentApiV1UsersMeCookieConsentPut({
        granted: [...local.granted],
        version: CONSENT_VERSION,
      })
        .then((saved) => markConsentSynced(saved.decided_at))
        .catch(() => {
          // Offline, or the request was refused. The browser's own answer is
          // still in force; the next mount tries again.
          settled.current = null;
        });
      return;
    }

    if (local.syncedAt !== account.decided_at) {
      adoptConsent({
        granted: asCategories(account.granted),
        version: account.version,
        decidedAt: account.decided_at,
      });
    }
  }, [user]);
};
