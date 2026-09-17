/**
 * Which of the two answers somebody typed.
 *
 * An authenticator shows a code as "123 456", and that is how people copy it;
 * a recovery code carries its own dashes and keeps them. Six digits once the
 * spacing is out is a live code, and anything else is one of the written ones.
 *
 * One rule, because two forms ask the question from a single field — turning
 * the factor off, and breaking glass — and a form that read it differently
 * would send the server the wrong one of the two.
 */
export interface SecondFactorAnswer {
  code?: string;
  recovery_code?: string;
}

export const classifySecondFactorAnswer = (entered: string): SecondFactorAnswer => {
  const trimmed = entered.trim();
  const compact = trimmed.replace(/[\s-]/g, "");
  return /^\d{6}$/.test(compact) ? { code: compact } : { recovery_code: trimmed };
};
