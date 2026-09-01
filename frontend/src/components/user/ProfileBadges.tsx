import { useTranslation } from "react-i18next";

import type { ProfileDecorationsOutput } from "@/api/generated/initiativeAPI.schemas";
import { resolveBadges } from "@/lib/profileDecorations";

/**
 * The badges a profile is wearing, in the order they were put on.
 *
 * Only the ones this build can draw: an id from a decoration this deployment
 * doesn't have simply isn't in the row, which is what keeps a profile readable
 * after the store stops offering something.
 */
export const ProfileBadges = ({
  decorations,
}: {
  decorations?: ProfileDecorationsOutput | null;
}) => {
  const { t } = useTranslation("profiles");
  const badges = resolveBadges(decorations);
  if (badges.length === 0) return null;

  return (
    <ul className="flex flex-wrap items-center gap-1.5">
      {badges.map((badge) => {
        const label = t(badge.labelKey);
        return (
          <li key={badge.id}>
            <img src={badge.src} alt={label} title={label} className="size-6" />
          </li>
        );
      })}
    </ul>
  );
};
