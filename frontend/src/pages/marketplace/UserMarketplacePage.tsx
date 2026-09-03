import { Link } from "@tanstack/react-router";
import { useTranslation } from "react-i18next";

import type { UserRead } from "@/api/generated/initiativeAPI.schemas";
import { Button } from "@/components/ui/button";
import { DecorationStore } from "@/components/user/DecorationStore";

/**
 * The marketplace a person buys from.
 *
 * Separate from a community's, because the buyer is different and so is what
 * "installed" means: a community's install is shared by everyone in it, and
 * this one is yours and travels with you across every community you are in.
 * It sits outside the `/c/{id}` tree for the same reason.
 *
 * Today it holds one shelf — profile packs. It is a page rather than a section
 * of settings because getting something and configuring it are different acts,
 * and settings is where you configure.
 */
export const UserMarketplacePage = ({ user }: { user: UserRead }) => {
  const { t } = useTranslation("profiles");

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="space-y-1">
          <h1 className="font-semibold text-3xl tracking-tight">{t("store.title")}</h1>
          <p className="text-muted-foreground text-sm">{t("store.description")}</p>
        </div>
        <Button variant="outline" asChild>
          <Link to="/profile">{t("store.manage")}</Link>
        </Button>
      </div>
      <DecorationStore user={user} />
    </div>
  );
};
