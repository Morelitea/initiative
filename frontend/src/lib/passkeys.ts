/**
 * Signing in with a passkey, in one place.
 *
 * Every conversation with the browser's credential API happens here: the page
 * asks for a sign-in and gets back what the server said, so what it has to
 * reason about is its own card rather than a ceremony. Two shapes of prompt go
 * through the same call — the modal one a button opens, and the quiet one that
 * waits inside the browser's own autofill — because the only thing that
 * separates them is a flag the credential API reads.
 */
import {
  browserSupportsWebAuthn,
  browserSupportsWebAuthnAutofill,
  type PublicKeyCredentialCreationOptionsJSON,
  type PublicKeyCredentialRequestOptionsJSON,
  startAuthentication,
  startRegistration,
  WebAuthnAbortService,
  WebAuthnError,
} from "@simplewebauthn/browser";

import { apiClient } from "@/api/client";
import type {
  PasskeyAuthenticationOptions,
  PasskeyRegistrationOptions,
  PasskeySignInFinishCredential,
  PasskeySignInResult,
  PasskeySignUpResult,
  PasskeySignUpStart,
  PasskeyStepUpFinishCredential,
  Token,
} from "@/api/generated/initiativeAPI.schemas";

/** Whether this browser can present a passkey at all. */
export const browserOffersPasskeys = (): boolean => browserSupportsWebAuthn();

/** Whether this browser can offer one from its own autofill, beside the saved
 *  passwords. Asked before the quiet prompt is started, so a browser without it
 *  is never sent a ceremony it would drop. */
export const browserOffersPasskeyAutofill = (): Promise<boolean> =>
  browserSupportsWebAuthnAutofill();

export interface PasskeySignInOptions {
  /** Wait inside the browser's autofill rather than opening a prompt. */
  conditional?: boolean;
  /** The ceremony belongs to an app: the answer is a way back to it rather
   *  than a session for this browser. */
  mobile?: boolean;
  /** What to call the device the app is running on, for the sign-in record. */
  deviceName?: string;
}

/**
 * Run a sign-in ceremony end to end.
 *
 * Nobody is named at the start: the authenticator offers what it holds for
 * this site, and the assertion that comes back says which credential answered.
 */
export const signInWithPasskey = async ({
  conditional = false,
  mobile = false,
  deviceName,
}: PasskeySignInOptions = {}): Promise<PasskeySignInResult> => {
  // Nothing to say at the start: the options are the same whoever asked and
  // whatever they are asking for. Where the answer goes — a session for this
  // browser, or a way back to the app that sent it — is settled at the finish.
  const begun = await apiClient.post<PasskeyAuthenticationOptions>(
    "/auth/passkeys/authenticate/begin",
    {}
  );
  // The server renders the options the way the credential API wants them, and
  // the browser's answer goes back as it came; the generated schema carries
  // both as open objects, so this is the one place the shapes are named.
  const credential = await startAuthentication({
    optionsJSON: begun.data.options as unknown as PublicKeyCredentialRequestOptionsJSON,
    useBrowserAutofill: conditional,
  });
  const finished = await apiClient.post<PasskeySignInResult>("/auth/passkeys/authenticate/finish", {
    credential: credential as unknown as PasskeySignInFinishCredential,
    mobile,
    device_name: deviceName ?? "",
  });
  return finished.data;
};

/**
 * Present a passkey against the session already open.
 *
 * The sign-in above names nobody, because nobody is signed in yet. This one is
 * for a community that asks a member already here for a passkey: the account
 * is known, so the server offers that account's own credentials and answers
 * with a session carrying what was presented — the same answer the
 * authenticator-code step-up gives, applied the same way.
 */
export const stepUpWithPasskey = async (): Promise<Token> => {
  const begun = await apiClient.post<PasskeyAuthenticationOptions>("/auth/step-up/passkey/begin");
  const credential = await startAuthentication({
    optionsJSON: begun.data.options as unknown as PublicKeyCredentialRequestOptionsJSON,
  });
  const finished = await apiClient.post<Token>("/auth/step-up/passkey/finish", {
    credential: credential as unknown as PasskeyStepUpFinishCredential,
  });
  return finished.data;
};

/**
 * Make an account whose way in is a key rather than a password.
 *
 * Two calls, like every ceremony: the first asks the server whether this
 * registration may happen at all — an address already taken, a missing invite,
 * a captcha — so the refusal comes before the authenticator is asked for
 * anything, and the second makes the account and signs it in. The details go
 * out again with the answer; nothing about the account exists in between.
 */
export const signUpWithPasskey = async (
  details: PasskeySignUpStart,
  inviteCode?: string
): Promise<PasskeySignUpResult> => {
  const query = inviteCode ? `?invite_code=${encodeURIComponent(inviteCode)}` : "";
  const begun = await apiClient.post<PasskeyRegistrationOptions>(
    `/auth/register/passkey/begin${query}`,
    details
  );
  const credential = await startRegistration({
    optionsJSON: begun.data.options as unknown as PublicKeyCredentialCreationOptionsJSON,
  });
  const finished = await apiClient.post<PasskeySignUpResult>(
    `/auth/register/passkey/finish${query}`,
    { ...details, credential }
  );
  return finished.data;
};

/**
 * Present a passkey against a break-glass request.
 *
 * Unlike the step-up above, nothing is added to the session: the challenge is
 * issued for the request that will spend it, so what the key proves belongs to
 * the grant being issued rather than to the browser holding it. The assertion
 * goes back in the break-glass body, beside the reason and the guild.
 */
export const assertForBreakGlass = async (): Promise<Record<string, unknown>> => {
  const begun = await apiClient.post<PasskeyAuthenticationOptions>(
    "/access-grants/break-glass/passkey"
  );
  const credential = await startAuthentication({
    optionsJSON: begun.data.options as unknown as PublicKeyCredentialRequestOptionsJSON,
  });
  return credential as unknown as Record<string, unknown>;
};

/** Put down whatever prompt is currently waiting. Only one ceremony runs at a
 *  time, so the quiet one has to go before a button's can start. */
export const cancelPendingPasskeyPrompt = (): void => WebAuthnAbortService.cancelCeremony();

/** The line to show for a prompt that ended without a credential, or null when
 *  there is nothing to say. */
export type PasskeyPromptMessageKey = "auth:login.passkeyCancelled" | "auth:login.passkeyFailed";

/**
 * Which line a prompt that produced nothing deserves.
 *
 * `startAuthentication` raises a {@link WebAuthnError} named after the
 * browser's own exception, and anything else landing in the same catch keeps
 * whatever name it had. A ceremony we put down ourselves — the quiet one,
 * stood aside for a button or gone with the page — is not a failure anybody
 * needs telling about, so it gets no line at all.
 */
export const describePasskeyPromptError = (error: unknown): PasskeyPromptMessageKey | null => {
  const name = error instanceof WebAuthnError || error instanceof Error ? error.name : "";
  if (name === "AbortError") return null;
  if (name === "NotAllowedError") return "auth:login.passkeyCancelled";
  return "auth:login.passkeyFailed";
};
