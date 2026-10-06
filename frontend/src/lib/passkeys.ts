/**
 * Signing in with a passkey, in one place.
 *
 * Every conversation with the browser's credential API happens here: the page
 * asks for a sign-in and gets back what the server said, so what it has to
 * reason about is its own card rather than a ceremony. Two shapes of prompt go
 * through the same call — the modal one a button opens, and the quiet one that
 * waits inside the browser's own autofill — because the only thing that
 * separates them is a flag the credential API reads.
 *
 * On Android the app runs the ceremony itself, through the platform's
 * credential manager, when the server names the app in its asset links. Where
 * it does not, the app goes to the phone's browser as it always has.
 */
import { Capacitor } from "@capacitor/core";
import {
  type CreatePasskeyOptions,
  type GetPasskeyOptions,
  Passkeys,
} from "@capawesome/capacitor-passkeys";
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

import { beginBreakGlassPasskey } from "@/api/generated/access-grants/access-grants";
import {
  beginPasskeySignIn,
  beginPasskeySignUp,
  beginPasskeyStepUp,
  finishPasskeySignIn,
  finishPasskeySignUp,
  finishPasskeyStepUp,
} from "@/api/generated/auth/auth";
import type {
  PasskeySignInFinishCredential,
  PasskeySignInResult,
  PasskeySignUpFinishCredential,
  PasskeySignUpResult,
  PasskeySignUpStart,
  PasskeyStepUpFinishCredential,
  Token,
} from "@/api/generated/initiativeAPI.schemas";
import { getStoredServerUrl } from "@/lib/serverStorage";
import { getItem, setItem } from "@/lib/storage";

/** Set when the phone would not let the app act for a server, which then
 *  goes straight to the browser until it lapses: long enough not to fail
 *  first on every press, short enough that a server put right is tried again. */
const APP_REFUSED_KEY = "initiative-passkey-app-refused";
const APP_REFUSED_TTL_MS = 24 * 60 * 60 * 1000;

/** The phone would not let the app run this ceremony for this server; the
 *  browser can. */
export class PasskeyNeedsBrowserError extends Error {
  constructor() {
    super("PASSKEY_NEEDS_BROWSER");
    this.name = "PasskeyNeedsBrowserError";
  }
}

const appHasPlugin = (): boolean =>
  Capacitor.getPlatform() === "android" && Capacitor.isPluginAvailable("Passkeys");

/**
 * Whether this app runs a passkey ceremony itself, rather than in the phone's
 * browser.
 *
 * Android only: an iOS app can act only for domains its build names. An older
 * app without the plugin, and a server the phone refused lately, use the
 * browser.
 */
export const appRunsPasskeys = (): boolean => {
  if (!appHasPlugin()) return false;
  try {
    const refused = JSON.parse(getItem(APP_REFUSED_KEY) ?? "null") as {
      server: string;
      at: number;
    } | null;
    return !(
      refused?.server === getStoredServerUrl() && Date.now() - refused.at < APP_REFUSED_TTL_MS
    );
  } catch {
    return true;
  }
};

/** Ask the app's plugin, giving its refusals the browser's names so one
 *  message table reads both. */
const viaApp = async <T>(call: () => Promise<T>): Promise<T> => {
  try {
    return await call();
  } catch (err) {
    const code = (err as { code?: string }).code ?? "";
    if (code === "DOMAIN_NOT_ASSOCIATED" || code === "NOT_SUPPORTED") {
      void setItem(
        APP_REFUSED_KEY,
        JSON.stringify({ server: getStoredServerUrl(), at: Date.now() })
      );
      throw new PasskeyNeedsBrowserError();
    }
    const error = new Error(code || "PASSKEY_FAILED");
    if (code === "CANCELED" || code === "NO_CREDENTIAL") error.name = "NotAllowedError";
    throw error;
  }
};

/** Present a credential, from the app or the browser. The server renders the
 *  options the way both want them; the generated schema carries them as open
 *  objects, so this and {@link createCredential} are where the shapes are named. */
const presentCredential = (options: unknown, conditional = false) =>
  appHasPlugin()
    ? viaApp(() => Passkeys.getPasskey(options as GetPasskeyOptions))
    : startAuthentication({
        optionsJSON: options as PublicKeyCredentialRequestOptionsJSON,
        useBrowserAutofill: conditional,
      });

/** Make a credential, from the app or the browser. */
export const createCredential = (options: unknown) =>
  appHasPlugin()
    ? viaApp(() => Passkeys.createPasskey(options as CreatePasskeyOptions))
    : startRegistration({ optionsJSON: options as PublicKeyCredentialCreationOptionsJSON });

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
  /** The app's challenge, which the code handed back to it is bound to. */
  codeChallenge?: string;
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
  codeChallenge,
}: PasskeySignInOptions = {}): Promise<PasskeySignInResult> => {
  // Nothing to say at the start: the options are the same whoever asked and
  // whatever they are asking for. Where the answer goes — a session for this
  // browser, or a way back to the app that sent it — is settled at the finish.
  const begun = await beginPasskeySignIn({});
  const credential = await presentCredential(begun.options, conditional);
  return finishPasskeySignIn({
    credential: credential as unknown as PasskeySignInFinishCredential,
    mobile,
    device_name: deviceName ?? "",
    code_challenge: codeChallenge ?? "",
  });
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
  const begun = await beginPasskeyStepUp();
  const credential = await presentCredential(begun.options);
  return finishPasskeyStepUp({
    credential: credential as unknown as PasskeyStepUpFinishCredential,
  });
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
  const params = inviteCode ? { invite_code: inviteCode } : undefined;
  const begun = await beginPasskeySignUp(details, params);
  const credential = await createCredential(begun.options);
  return finishPasskeySignUp(
    { ...details, credential: credential as unknown as PasskeySignUpFinishCredential },
    params
  );
};

/**
 * Present a passkey against a break-glass request.
 *
 * Unlike the step-up above, nothing is added to the session: the challenge is
 * issued for the request that will spend it, so what the key proves belongs to
 * the grant being issued rather than to the browser holding it. The assertion
 * goes back in the break-glass body, beside the reason and the community.
 */
export const assertForBreakGlass = async (): Promise<Record<string, unknown>> => {
  const begun = await beginBreakGlassPasskey();
  const credential = await presentCredential(begun.options);
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
  // The page offers the browser instead, which says more than a line would.
  if (name === "AbortError" || error instanceof PasskeyNeedsBrowserError) return null;
  if (name === "NotAllowedError") return "auth:login.passkeyCancelled";
  return "auth:login.passkeyFailed";
};
