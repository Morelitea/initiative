import { useTranslation } from "react-i18next";

import { safetyCode } from "@/crypto/safetyCode";

/**
 * One device's key, drawn as the pictures a person compares.
 *
 * The emoji is decoration and the name is the text: a screen reader reads the
 * names in order, which is the same comparison somebody makes by eye, and it
 * is also what two people read to each other over a phone.
 */
export const SafetyCode = ({ fingerprint }: { fingerprint: string }) => {
  const { t } = useTranslation("messages");
  const code = safetyCode(fingerprint);
  if (code.length === 0) return null;

  return (
    <ol className="flex flex-wrap gap-x-4 gap-y-2" aria-label={t("historyRequest.codeLabel")}>
      {code.map((entry, index) => (
        <li
          // biome-ignore lint/suspicious/noArrayIndexKey: a code is a sequence, and the same picture can come up twice in it — position is the identity
          key={index}
          className="flex w-16 flex-col items-center gap-0.5"
        >
          <span className="text-3xl leading-none" aria-hidden>
            {entry.emoji}
          </span>
          <span className="text-center text-[0.7rem] text-muted-foreground leading-tight">
            {t(`safetyEmoji.${entry.name}`)}
          </span>
        </li>
      ))}
    </ol>
  );
};
