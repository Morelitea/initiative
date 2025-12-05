import { useEffect, useMemo, useState } from "react";
import { Loader2 } from "lucide-react";
import { useNavigate, useSearchParams } from "react-router-dom";

import { Button } from "@/components/ui/button";
import { useGuilds } from "@/hooks/useGuilds";
import { useAuth } from "@/hooks/useAuth";

const normalizeTarget = (raw: string): string => {
  const decoded = decodeURIComponent(raw);
  if (!decoded) {
    return "/";
  }
  return decoded.startsWith("/") ? decoded : `/${decoded}`;
};

export const NavigatePage = () => {
  const { user, loading: authLoading } = useAuth();
  const { activeGuildId, switchGuild } = useGuilds();
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const [error, setError] = useState<string | null>(null);
  const [isProcessing, setIsProcessing] = useState(true);

  const guildParam = searchParams.get("guild_id");
  const targetParam = searchParams.get("target");

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
      setError("Please sign in again to follow this link.");
      setIsProcessing(false);
      return;
    }
    if (!guildParam || !destination) {
      setError("This link is missing destination details.");
      setIsProcessing(false);
      return;
    }
    let parsedGuildId = Number(guildParam);
    if (!Number.isFinite(parsedGuildId)) {
      parsedGuildId = Number.parseInt(guildParam, 10);
    }
    if (!Number.isFinite(parsedGuildId)) {
      setError("Invalid guild id in link.");
      setIsProcessing(false);
      return;
    }

    setError(null);
    setIsProcessing(true);
    const performNavigation = async () => {
      try {
        if (activeGuildId !== parsedGuildId) {
          await switchGuild(parsedGuildId);
        }
        navigate(destination, { replace: true });
      } catch (err) {
        console.error("Failed to follow smart link", err);
        setError("Unable to switch guild for this link.");
        setIsProcessing(false);
      }
    };
    void performNavigation();
  }, [authLoading, user, guildParam, activeGuildId, switchGuild, navigate, destination]);

  if (error) {
    return (
      <div className="flex min-h-screen flex-col items-center justify-center gap-4 px-6 text-center">
        <p className="text-destructive text-base font-medium">{error}</p>
        <Button onClick={() => navigate("/", { replace: true })}>Go back home</Button>
      </div>
    );
  }

  return (
    <div className="flex min-h-screen flex-col items-center justify-center gap-3 px-6 text-center">
      <Loader2 className="text-muted-foreground h-6 w-6 animate-spin" />
      <p className="text-muted-foreground text-sm">
        {isProcessing ? "Redirecting you to the right guild…" : "Finalizing redirect…"}
      </p>
    </div>
  );
};
