import { Link, useParams } from "@tanstack/react-router";
import { useTranslation } from "react-i18next";

import type { LoginProviderEntry } from "@/api/generated/initiativeAPI.schemas";
import { LogoIcon } from "@/components/LogoIcon";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { useGuildLoginProviders } from "@/hooks/useGuildAuthPolicy";
import { useServer } from "@/hooks/useServer";

/**
 * A guild's own sign-in page (per-guild auth posture) — the URL a guild admin
 * shares with members. Offers the guild's configured identity providers;
 * completing one signs the user in, admits them to the guild, and lands them
 * on the guild's home. Unauthenticated by design; a signed-in visitor just
 * adds the provider to their session (step-up union).
 */
export const GuildLoginPage = () => {
  const { t } = useTranslation(["auth", "common"]);
  const params = useParams({ strict: false }) as { guildId?: string };
  const guildId = params.guildId ? Number(params.guildId) : 0;
  const { isNativePlatform } = useServer();

  const providersQuery = useGuildLoginProviders(guildId, {
    enabled: guildId > 0 && !isNativePlatform,
  });
  const providers = providersQuery.data?.providers ?? [];
  const guildName = providersQuery.data?.guild_name ?? null;

  const signIn = (entry: LoginProviderEntry) => {
    const next = `/g/${guildId}`;
    window.location.href = `${entry.login_url}?next=${encodeURIComponent(next)}`;
  };

  return (
    <div className="flex min-h-screen items-center justify-center bg-muted/60 px-4 py-12">
      <Card className="w-full max-w-md shadow-sm">
        <CardHeader className="items-center text-center">
          <LogoIcon className="mb-2 h-10 w-10" />
          <CardTitle>{guildName ?? t("guildLogin.title")}</CardTitle>
          <CardDescription>{t("guildLogin.subtitle")}</CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          {isNativePlatform ? (
            <p className="text-center text-muted-foreground text-sm">
              {t("guildLogin.nativeUnsupported")}
            </p>
          ) : providersQuery.isLoading ? (
            <p className="text-center text-muted-foreground text-sm">{t("common:loading")}</p>
          ) : providers.length === 0 ? (
            <p className="text-center text-muted-foreground text-sm">
              {t("guildLogin.noProviders")}
            </p>
          ) : (
            providers.map((provider) => (
              <Button
                key={provider.slug}
                type="button"
                variant="outline"
                className="w-full"
                onClick={() => signIn(provider)}
              >
                {t("login.continueWith", { provider: provider.display_name })}
              </Button>
            ))
          )}
        </CardContent>
        <CardFooter className="justify-center">
          <Link className="text-primary text-sm underline-offset-4 hover:underline" to="/login">
            {t("guildLogin.otherSignIn")}
          </Link>
        </CardFooter>
      </Card>
    </div>
  );
};
