import { useTranslation } from "react-i18next";

import { ContactPersonRow } from "@/components/contacts/ContactPersonRow";
import { Button } from "@/components/ui/button";
import { useIgnoredAccounts, useStopIgnoring } from "@/hooks/useDirectMessages";

/**
 * The accounts this person has chosen not to hear from.
 *
 * The lead line is four clauses because the word invites three wrong
 * expectations: that only notifications stop, that it runs both ways, and that
 * it hides them. It says nothing about what the other account sees.
 */
export const IgnoredAccountsSection = () => {
  const { t } = useTranslation("settings");
  const { data } = useIgnoredAccounts();
  const stopIgnoring = useStopIgnoring();

  const items = data?.items ?? [];

  return (
    <div className="space-y-3">
      <p className="text-muted-foreground text-sm">{t("privacy.ignored.description")}</p>
      {items.length === 0 ? (
        <p className="text-muted-foreground text-sm">{t("privacy.ignored.empty")}</p>
      ) : (
        <ul className="divide-y">
          {items.map((account) => (
            <ContactPersonRow
              key={account.user_id}
              user={{
                id: account.user_id,
                username: account.username,
                discriminator: account.discriminator,
                avatar_url: account.avatar_url,
              }}
            >
              <Button
                variant="outline"
                size="sm"
                onClick={() => stopIgnoring.mutate({ userId: account.user_id })}
                disabled={stopIgnoring.isPending}
              >
                {t("privacy.ignored.stop")}
              </Button>
            </ContactPersonRow>
          ))}
        </ul>
      )}
    </div>
  );
};
