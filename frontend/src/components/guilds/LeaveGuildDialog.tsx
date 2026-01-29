import { useEffect, useState } from "react";
import { Loader2, AlertTriangle } from "lucide-react";
import { toast } from "sonner";

import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { apiClient } from "@/api/client";
import type { Guild, LeaveGuildEligibilityResponse } from "@/types/api";
import { useGuilds } from "@/hooks/useGuilds";

interface LeaveGuildDialogProps {
  guild: Guild;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export const LeaveGuildDialog = ({ guild, open, onOpenChange }: LeaveGuildDialogProps) => {
  const { guilds, refreshGuilds, switchGuild, activeGuildId } = useGuilds();
  const [loading, setLoading] = useState(true);
  const [leaving, setLeaving] = useState(false);
  const [eligibility, setEligibility] = useState<LeaveGuildEligibilityResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) {
      setEligibility(null);
      setError(null);
      setLoading(true);
      return;
    }

    const checkEligibility = async () => {
      setLoading(true);
      setError(null);
      try {
        const response = await apiClient.get<LeaveGuildEligibilityResponse>(
          `/guilds/${guild.id}/leave/eligibility`
        );
        setEligibility(response.data);
      } catch (err) {
        console.error("Failed to check leave eligibility", err);
        setError("Failed to check eligibility. Please try again.");
      } finally {
        setLoading(false);
      }
    };

    void checkEligibility();
  }, [open, guild.id]);

  const handleLeave = async () => {
    setLeaving(true);
    try {
      await apiClient.delete(`/guilds/${guild.id}/leave`);

      // Switch to another guild if leaving the active one
      if (activeGuildId === guild.id) {
        const otherGuild = guilds.find((g) => g.id !== guild.id);
        if (otherGuild) {
          await switchGuild(otherGuild.id);
        }
      }

      await refreshGuilds();
      toast.success(`Left ${guild.name}`);
      onOpenChange(false);
    } catch (err) {
      console.error("Failed to leave guild", err);
      toast.error("Failed to leave guild. Please try again.");
    } finally {
      setLeaving(false);
    }
  };

  const renderContent = () => {
    if (loading) {
      return (
        <div className="flex items-center justify-center py-8">
          <Loader2 className="text-muted-foreground h-6 w-6 animate-spin" />
        </div>
      );
    }

    if (error) {
      return (
        <Alert variant="destructive">
          <AlertTriangle className="h-4 w-4" />
          <AlertTitle>Error</AlertTitle>
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      );
    }

    if (!eligibility) {
      return null;
    }

    if (!eligibility.can_leave) {
      return (
        <Alert variant="destructive">
          <AlertTriangle className="h-4 w-4" />
          <AlertTitle>Cannot leave guild</AlertTitle>
          <AlertDescription>
            <ul className="mt-2 list-inside list-disc space-y-1">
              {eligibility.is_last_admin && (
                <li>
                  You are the last admin of this guild. Promote another member to admin first.
                </li>
              )}
              {eligibility.sole_pm_initiatives.length > 0 && (
                <li>
                  You are the sole project manager of:{" "}
                  <span className="font-medium">{eligibility.sole_pm_initiatives.join(", ")}</span>.
                  Promote another member to project manager first.
                </li>
              )}
            </ul>
          </AlertDescription>
        </Alert>
      );
    }

    return (
      <AlertDialogDescription>
        You will lose access to all initiatives and projects in{" "}
        <span className="font-medium">{guild.name}</span>. This action cannot be undone.
      </AlertDialogDescription>
    );
  };

  const canLeave = eligibility?.can_leave && !loading && !error;

  return (
    <AlertDialog open={open} onOpenChange={onOpenChange}>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>Leave {guild.name}?</AlertDialogTitle>
        </AlertDialogHeader>
        {renderContent()}
        <AlertDialogFooter>
          <AlertDialogCancel disabled={leaving}>Cancel</AlertDialogCancel>
          {canLeave && (
            <AlertDialogAction
              onClick={handleLeave}
              disabled={leaving}
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
            >
              {leaving ? (
                <>
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  Leaving...
                </>
              ) : (
                "Leave Guild"
              )}
            </AlertDialogAction>
          )}
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
};
