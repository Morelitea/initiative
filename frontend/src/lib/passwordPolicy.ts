import i18n from "@/i18n";

/**
 * Password policy — mirror of `backend/app/core/password_policy.py`.
 *
 * Length is the only policy we can validate client-side; the breach
 * check runs server-side (HIBP k-anonymity) on submit and surfaces
 * via the `PASSWORD_BREACHED` error code mapped in `errors.json`.
 *
 * Keep `PASSWORD_MIN_LENGTH` in sync with the backend constant. We
 * don't share it via the OpenAPI schema because the constraint is
 * enforced in the policy module, not at the schema layer (see the
 * comment in the backend module for why).
 */
export const PASSWORD_MIN_LENGTH = 12;

/**
 * Loose ``t`` binding so this module doesn't carry the strict
 * literal-key type that ``react-i18next``'s ``useTranslation`` emits.
 * Same trick ``errorMessage.ts`` uses — the namespaces we look up
 * (``auth``) are eagerly loaded by every caller of this module
 * (Register / Reset / Settings pages already use the ``auth`` ns),
 * so a runtime miss isn't a risk worth paying the type-cost for.
 */
const translate = i18n.t.bind(i18n) as (key: string) => string;

/**
 * Return an i18n'd error message if `password` fails the local part of
 * the policy, or `null` if it passes. Returns `null` for the empty
 * string so we don't show an error before the user has typed
 * anything — surface the requirement as a helper hint instead.
 */
export function validatePasswordLocal(password: string): string | null {
  if (password.length === 0) {
    return null;
  }
  if (password.length < PASSWORD_MIN_LENGTH) {
    return translate("auth:passwordPolicy.minLength");
  }
  return null;
}
