/**
 * One line for a passkey prompt that produced nothing.
 *
 * Two cards run a sign-in ceremony — the sign-in card, and the relay card an
 * app sends a phone's browser to — and both report the same way: what the
 * server said when it answered, this app's own wording when the browser is
 * what ended the prompt, and nothing at all for a prompt the page itself
 * stood down.
 */
import { isAxiosError } from "axios";
import type { TFunction } from "i18next";

import { getErrorMessage } from "@/lib/errorMessage";
import { describePasskeyPromptError } from "@/lib/passkeys";

/** The namespaces a card that runs a ceremony translates against. */
export type PasskeyFailureT = TFunction<readonly ["auth", "common", "errors"]>;

/** What to put on the card, or null when there is nothing worth saying. */
export const passkeyFailureMessage = (error: unknown, t: PasskeyFailureT): string | null => {
  if (isAxiosError(error)) return getErrorMessage(error, "auth:login.passkeyFailed");
  const key = describePasskeyPromptError(error);
  return key ? t(key) : null;
};
