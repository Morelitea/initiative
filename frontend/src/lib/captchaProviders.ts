/**
 * The spam checks a deployment can put in front of sign-up.
 *
 * Two surfaces need to agree about these: the widget, which loads the
 * vendor's script, and the cookie notice, which names the vendor whose cookie
 * the reader is about to be given. One record rather than a list each, so an
 * operator who sets `CAPTCHA_PROVIDER` to something not in here gets the same
 * answer from both — the widget says so, and the notice claims nothing.
 */

export interface CaptchaProvider {
  /** The vendor's own name, written the way they write it. Not translated. */
  readonly name: string;
  /** Where the widget's script comes from. */
  readonly scriptUrl: string;
}

export const CAPTCHA_PROVIDERS: Readonly<Record<string, CaptchaProvider>> = {
  // `render=explicit` (hCaptcha + reCAPTCHA) gives a deterministic init point
  // so the SDK doesn't auto-render any accidental `.h-captcha` / `.g-recaptcha`
  // markup elsewhere on the page. Turnstile already requires explicit render.
  hcaptcha: {
    name: "hCaptcha",
    scriptUrl: "https://js.hcaptcha.com/1/api.js?render=explicit",
  },
  turnstile: {
    name: "Cloudflare Turnstile",
    scriptUrl: "https://challenges.cloudflare.com/turnstile/v0/api.js",
  },
  recaptcha: {
    name: "Google reCAPTCHA",
    scriptUrl: "https://www.google.com/recaptcha/api.js?render=explicit",
  },
};

/** The provider the deployment named, or undefined where the name is not one
 *  of ours — the backend filters to the same three, so this is the typo case. */
export const captchaProvider = (provider: string): CaptchaProvider | undefined =>
  CAPTCHA_PROVIDERS[provider];
