import { useEffect, useMemo, useState } from "react";
import { Loader2 } from "lucide-react";
import { useRouter, useSearch } from "@tanstack/react-router";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";
import { useGuilds } from "@/hooks/useGuilds";
import { useAuth } from "@/hooks/useAuth";
import { isGuildScopedPath, guildPath } from "@/lib/guildUrl";

const normalizeTarget = (raw: string): string => {
  const decoded = decodeURIComponent(raw);
  if (!decoded) {
    return "/";
  }
  return decoded.startsWith("/") ? decoded : `/${decoded}`;
};

export const NavigatePage = () => {
  const { t } = useTranslation("nav");
  const { user, loading: authLoading } = useAuth();
  const { guilds, activeGuildId, switchGuild } = useGuilds();
  const searchParams = useSearch({ strict: false }) as { guild_id?: string; target?: string };
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);
  const [isProcessing, setIsProcessing] = useState(true);

  const guildParam = searchParams.guild_id;
  const targetParam = searchParams.target;

  const destination = useMemo(() => {
    if (!targetParam) {
      return null;
    }
    try {
      return normalizeTarget(targetParam);
    } catch {
      return null;
    }
  }, [targetParam]);

  useEffect(() => {
    if (authLoading) {
      return;
    }
    if (!user) {
      setError(t("navigate.signInRequired"));
      setIsProcessing(false);
      return;
    }
    if (!guildParam || !destination) {
      setError(t("navigate.missingDestination"));
      setIsProcessing(false);
      return;
    }
    let parsedGuildId = Number(guildParam);
    if (!Number.isFinite(parsedGuildId)) {
      parsedGuildId = Number.parseInt(guildParam, 10);
    }
    if (!Number.isFinite(parsedGuildId)) {
      setError(t("navigate.invalidGuildId"));
      setIsProcessing(false);
      return;
    }

    // Check if user has access to this guild
    const hasAccess = guilds.some((g) => g.id === parsedGuildId);
    if (!hasAccess) {
      setError(t("navigate.noAccess"));
      setIsProcessing(false);
      return;
    }

    setError(null);
    setIsProcessing(true);

    // Redirect to new guild-scoped URL format if the target isn't already guild-scoped
    const finalDestination = isGuildScopedPath(destination)
      ? destination
      : guildPath(parsedGuildId, destination);

    const performNavigation = async () => {
      try {
        // Sync guild context in background (but URL already has guild info)
        if (activeGuildId !== parsedGuildId) {
          await switchGuild(parsedGuildId);
        }
        router.navigate({ to: finalDestination, replace: true });
      } catch (err) {
        console.error("Failed to follow smart link", err);
        setError(t("navigate.switchError"));
        setIsProcessing(false);
      }
    };
    void performNavigation();
  }, [authLoading, user, guilds, guildParam, activeGuildId, switchGuild, router, destination, t]);

  if (error) {
    return (
      <div className="flex min-h-screen flex-col items-center justify-center gap-4 px-6 text-center">
        <p className="text-destructive text-base font-medium">{error}</p>
        <Button onClick={() => router.navigate({ to: "/", replace: true })}>
          {t("navigate.goHome")}
        </Button>
      </div>
    );
  }

  return (
    <div className="flex min-h-screen flex-col items-center justify-center gap-3 px-6 text-center">
      <Loader2 className="text-muted-foreground h-6 w-6 animate-spin" />
      <p className="text-muted-foreground text-sm">
        {isProcessing ? t("navigate.redirecting") : t("navigate.finalizing")}
      </p>
    </div>
  );
};
