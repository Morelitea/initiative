import { useState } from "react";
import { Link, Navigate, useParams } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { Loader2, Settings } from "lucide-react";

import { apiClient } from "@/api/client";
import { DocumentsView } from "./DocumentsPage";
import { ProjectsView } from "./ProjectsPage";
import { InitiativeColorDot } from "@/lib/initiativeColors";
import { Button } from "@/components/ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Badge } from "@/components/ui/badge";
import { useAuth } from "@/hooks/useAuth";
import { useGuilds } from "@/hooks/useGuilds";
import { getRoleLabel, useRoleLabels } from "@/hooks/useRoleLabels";
import { Markdown } from "@/components/Markdown";
import type { Initiative } from "@/types/api";

export const InitiativeDetailPage = () => {
  const { initiativeId: initiativeIdParam } = useParams({ strict: false }) as {
    initiativeId: string;
  };
  const parsedInitiativeId = Number(initiativeIdParam);
  const hasValidInitiativeId = Number.isFinite(parsedInitiativeId);
  const initiativeId = hasValidInitiativeId ? parsedInitiativeId : 0;
  const { user } = useAuth();
  const { activeGuild, activeGuildId } = useGuilds();
  const { data: roleLabels } = useRoleLabels();
  const projectManagerLabel = getRoleLabel("project_manager", roleLabels);
  const memberLabel = getRoleLabel("member", roleLabels);
  const guildAdminLabel = getRoleLabel("admin", roleLabels);

  const initiativesQuery = useQuery<Initiative[]>({
    queryKey: ["initiatives", { guildId: activeGuildId }],
    queryFn: async () => {
      const response = await apiClient.get<Initiative[]>("/initiatives/");
      return response.data;
    },
    enabled: hasValidInitiativeId,
  });

  const initiative =
    hasValidInitiativeId && initiativesQuery.data
      ? (initiativesQuery.data.find((item) => item.id === initiativeId) ?? null)
      : null;
  const isGuildAdmin = activeGuild?.role === "admin";
  const membership = initiative?.members.find((member) => member.user.id === user?.id) ?? null;
  const isInitiativeManager = membership?.role === "project_manager";
  const canManageInitiative = Boolean(isGuildAdmin || isInitiativeManager);

  const [activeTab, setActiveTab] = useState<"documents" | "projects">("documents");

  const memberCount = initiative?.members.length ?? 0;

  const roleBadgeLabel = membership
    ? membership.role === "project_manager"
      ? projectManagerLabel
      : memberLabel
    : isGuildAdmin
      ? guildAdminLabel
      : null;

  if (!hasValidInitiativeId) {
    return <Navigate to="/initiatives" replace />;
  }

  if (initiativesQuery.isLoading || !initiativesQuery.data) {
    return (
      <div className="text-muted-foreground flex items-center gap-2 text-sm">
        <Loader2 className="h-4 w-4 animate-spin" />
        Loading initiative…
      </div>
    );
  }

  if (!initiative) {
    return (
      <div className="space-y-4">
        <Button variant="link" size="sm" asChild className="px-0">
          <Link to="/initiatives">← Back to My Initiatives</Link>
        </Button>
        <div className="rounded-lg border p-6">
          <h1 className="text-2xl font-semibold">Initiative not found</h1>
          <p className="text-muted-foreground">
            The initiative you&apos;re looking for doesn&apos;t exist or you no longer have access.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="space-y-4">
          <Button variant="link" size="sm" asChild className="px-0">
            <Link to="/initiatives">← Back to My Initiatives</Link>
          </Button>
          <div className="flex flex-wrap items-center gap-3">
            <InitiativeColorDot color={initiative.color} className="h-4 w-4" />
            <h1 className="text-3xl font-semibold tracking-tight">{initiative.name}</h1>
            {initiative.is_default ? <Badge variant="outline">Default</Badge> : null}
            {roleBadgeLabel ? <Badge variant="secondary">{roleBadgeLabel}</Badge> : null}
          </div>
          {initiative.description ? (
            <Markdown content={initiative.description} className="text-muted-foreground" />
          ) : (
            <p className="text-muted-foreground text-sm">No description yet.</p>
          )}
          <div className="text-muted-foreground flex flex-wrap items-center gap-4 text-sm">
            <span>
              {memberCount} {memberCount === 1 ? "member" : "members"}
            </span>
            <span>Updated {new Date(initiative.updated_at).toLocaleDateString()}</span>
          </div>
        </div>
        <div className="flex flex-wrap gap-2">
          {canManageInitiative ? (
            <Button variant="outline" asChild>
              <Link
                to="/initiatives/$initiativeId/settings"
                params={{ initiativeId: String(initiative.id) }}
              >
                <Settings className="mr-2 h-4 w-4" />
                Initiative settings
              </Link>
            </Button>
          ) : null}
        </div>
      </div>

      <Tabs
        value={activeTab}
        onValueChange={(value) => setActiveTab(value as "documents" | "projects")}
      >
        <TabsList className="grid w-full max-w-xs grid-cols-2">
          <TabsTrigger value="documents">Documents</TabsTrigger>
          <TabsTrigger value="projects">Projects</TabsTrigger>
        </TabsList>
        <TabsContent value="documents" className="mt-6">
          <DocumentsView key={`documents-${initiative.id}`} fixedInitiativeId={initiative.id} />
        </TabsContent>
        <TabsContent value="projects" className="mt-6">
          <ProjectsView key={`projects-${initiative.id}`} fixedInitiativeId={initiative.id} />
        </TabsContent>
      </Tabs>
    </div>
  );
};
