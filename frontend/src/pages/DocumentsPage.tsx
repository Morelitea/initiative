import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { formatDistanceToNow } from "date-fns";
import { Loader2, Plus, ScrollText } from "lucide-react";
import { toast } from "sonner";

import { apiClient } from "@/api/client";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Badge } from "@/components/ui/badge";
import { InitiativeColorDot } from "@/lib/initiativeColors";
import { useAuth } from "@/hooks/useAuth";
import type { DocumentRead, DocumentSummary, Initiative } from "@/types/api";

const INITIATIVE_FILTER_ALL = "all";

export const DocumentsPage = () => {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { user } = useAuth();
  const [initiativeFilter, setInitiativeFilter] = useState<string>(INITIATIVE_FILTER_ALL);
  const [searchQuery, setSearchQuery] = useState("");

  const documentsQuery = useQuery<DocumentSummary[]>({
    queryKey: ["documents", { initiative: initiativeFilter, search: searchQuery }],
    queryFn: async () => {
      const params: Record<string, string> = {};
      if (initiativeFilter !== INITIATIVE_FILTER_ALL) {
        params.initiative_id = initiativeFilter;
      }
      if (searchQuery.trim()) {
        params.search = searchQuery.trim();
      }
      const response = await apiClient.get<DocumentSummary[]>("/documents/", { params });
      return response.data;
    },
  });

  const initiativesQuery = useQuery<Initiative[]>({
    queryKey: ["initiatives"],
    queryFn: async () => {
      const response = await apiClient.get<Initiative[]>("/initiatives/");
      return response.data;
    },
  });

  const manageableInitiatives = useMemo(() => {
    const initiatives = initiativesQuery.data ?? [];
    if (!user) {
      return [];
    }
    if (user.role === "admin") {
      return initiatives;
    }
    return initiatives.filter((initiative) =>
      initiative.members.some(
        (member) => member.user.id === user.id && member.role === "project_manager"
      )
    );
  }, [initiativesQuery.data, user]);

  const [createDialogOpen, setCreateDialogOpen] = useState(false);
  const [newTitle, setNewTitle] = useState("");
  const [newInitiativeId, setNewInitiativeId] = useState<string>("");
  const canCreateDocuments = manageableInitiatives.length > 0;

  useEffect(() => {
    if (!createDialogOpen) {
      return;
    }
    if (!newInitiativeId && manageableInitiatives.length > 0) {
      setNewInitiativeId(String(manageableInitiatives[0].id));
    }
  }, [createDialogOpen, manageableInitiatives, newInitiativeId]);

  const createDocument = useMutation({
    mutationFn: async () => {
      const trimmedTitle = newTitle.trim();
      if (!trimmedTitle) {
        throw new Error("Document title is required");
      }
      if (!newInitiativeId) {
        throw new Error("Select an initiative");
      }
      const payload = {
        title: trimmedTitle,
        initiative_id: Number(newInitiativeId),
      };
      const response = await apiClient.post<DocumentRead>("/documents/", payload);
      return response.data;
    },
    onSuccess: (document) => {
      toast.success("Document created");
      setCreateDialogOpen(false);
      setNewTitle("");
      void queryClient.invalidateQueries({ queryKey: ["documents"] });
      navigate(`/documents/${document.id}`);
    },
    onError: (error) => {
      const message =
        error instanceof Error ? error.message : "Unable to create document right now.";
      toast.error(message);
    },
  });

  const initiatives = initiativesQuery.data ?? [];

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Documents</h1>
          <p className="text-sm text-muted-foreground">
            Keep initiative knowledge organized and attach docs to projects.
          </p>
        </div>
        <Button
          type="button"
          onClick={() => setCreateDialogOpen(true)}
          disabled={!canCreateDocuments}
        >
          <Plus className="mr-2 h-4 w-4" />
          New document
        </Button>
      </div>
      <div className="grid gap-3 sm:grid-cols-[240px_1fr]">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:gap-4">
          <div className="w-full space-y-2">
            <Label htmlFor="document-initiative-filter">Initiative</Label>
            <Select
              value={initiativeFilter}
              onValueChange={(value) => setInitiativeFilter(value)}
              disabled={initiativesQuery.isLoading}
            >
              <SelectTrigger id="document-initiative-filter">
                <SelectValue placeholder="All initiatives" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={INITIATIVE_FILTER_ALL}>All initiatives</SelectItem>
                {initiatives.map((initiative) => (
                  <SelectItem key={initiative.id} value={String(initiative.id)}>
                    {initiative.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="w-full space-y-2">
            <Label htmlFor="document-search">Search</Label>
            <Input
              id="document-search"
              type="search"
              placeholder="Search documents"
              value={searchQuery}
              onChange={(event) => setSearchQuery(event.target.value)}
            />
          </div>
        </div>
      </div>

      {documentsQuery.isLoading ? (
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" />
          Loading documents…
        </div>
      ) : null}

      {documentsQuery.isError ? (
        <p className="text-sm text-destructive">Unable to load documents right now.</p>
      ) : null}

      {!documentsQuery.isLoading && !documentsQuery.isError ? (
        documentsQuery.data && documentsQuery.data.length > 0 ? (
          <div className="grid gap-4 lg:grid-cols-2">
            {documentsQuery.data.map((document) => (
              <Card key={document.id} className="flex h-full flex-col overflow-hidden">
                <div className="relative aspect-[4/3] w-full border-b border-border bg-muted">
                  {document.featured_image_url ? (
                    <img
                      src={document.featured_image_url}
                      alt=""
                      loading="lazy"
                      className="h-full w-full object-cover"
                    />
                  ) : (
                    <div className="flex h-full items-center justify-center text-muted-foreground">
                      <ScrollText className="h-10 w-10" />
                    </div>
                  )}
                </div>
                <CardHeader className="flex flex-col gap-2">
                  <CardTitle className="flex items-center justify-between gap-3 text-xl">
                    <Link
                      to={`/documents/${document.id}`}
                      className="line-clamp-1 font-semibold hover:text-primary"
                    >
                      {document.title}
                    </Link>
                    <Badge variant="secondary">
                      {document.projects.length} project
                      {document.projects.length === 1 ? "" : "s"}
                    </Badge>
                  </CardTitle>
                  {document.initiative ? (
                    <CardDescription className="flex items-center gap-2">
                      <InitiativeColorDot color={document.initiative.color} />
                      <span>{document.initiative.name}</span>
                    </CardDescription>
                  ) : null}
                </CardHeader>
                <CardContent className="flex flex-1 flex-col justify-between gap-4">
                  <div className="space-y-2">
                    <p className="text-sm text-muted-foreground">
                      Updated{" "}
                      {formatDistanceToNow(new Date(document.updated_at), {
                        addSuffix: true,
                      })}
                    </p>
                    {document.projects.length > 0 ? (
                      <div className="space-y-1">
                        {document.projects.slice(0, 3).map((link) => (
                          <Link
                            key={`${document.id}-${link.project_id}`}
                            to={`/projects/${link.project_id}`}
                            className="block text-sm text-primary hover:underline"
                          >
                            {link.project_name ?? `Project #${link.project_id}`}
                          </Link>
                        ))}
                        {document.projects.length > 3 ? (
                          <p className="text-xs text-muted-foreground">
                            +{document.projects.length - 3} more
                          </p>
                        ) : null}
                      </div>
                    ) : (
                      <p className="text-sm text-muted-foreground">
                        Not attached to any projects yet.
                      </p>
                    )}
                  </div>
                  <div>
                    <Button asChild variant="outline" size="sm">
                      <Link to={`/documents/${document.id}`}>Open document</Link>
                    </Button>
                  </div>
                </CardContent>
              </Card>
            ))}
          </div>
        ) : (
          <Card>
            <CardHeader>
              <CardTitle>No documents yet</CardTitle>
              <CardDescription>
                Create your first initiative document to share briefs, decisions, or guides.
              </CardDescription>
            </CardHeader>
            <CardContent>
              <Button onClick={() => setCreateDialogOpen(true)} disabled={!canCreateDocuments}>
                Start writing
              </Button>
            </CardContent>
          </Card>
        )
      ) : null}

      <Dialog open={createDialogOpen} onOpenChange={setCreateDialogOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>New document</DialogTitle>
            <DialogDescription>
              Documents live inside an initiative and can be attached to projects later.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="new-document-title">Title</Label>
              <Input
                id="new-document-title"
                value={newTitle}
                onChange={(event) => setNewTitle(event.target.value)}
                placeholder="Product launch brief"
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="new-document-initiative">Initiative</Label>
              <Select
                value={newInitiativeId}
                onValueChange={(value) => setNewInitiativeId(value)}
                disabled={!canCreateDocuments}
              >
                <SelectTrigger id="new-document-initiative">
                  <SelectValue placeholder="Select initiative" />
                </SelectTrigger>
                <SelectContent>
                  {manageableInitiatives.map((initiative) => (
                    <SelectItem key={initiative.id} value={String(initiative.id)}>
                      {initiative.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>
          <DialogFooter>
            <Button
              type="button"
              onClick={() => createDocument.mutate()}
              disabled={createDocument.isPending || !newTitle.trim() || !newInitiativeId}
            >
              {createDocument.isPending ? (
                <>
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  Creating…
                </>
              ) : (
                "Create document"
              )}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
};
