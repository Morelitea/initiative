import { type ChangeEvent, type FormEvent, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { useImportEnvelopeApiV1GGuildIdImportsEnvelopePost } from "@/api/generated/imports/imports";
import type { Tool } from "@/api/generated/initiativeAPI.schemas";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useActiveGuildId } from "@/hooks/useActiveGuildId";
import { useInitiativeAccess } from "@/hooks/useInitiativeAccess";
import { useInitiatives } from "@/hooks/useInitiatives";
import { toast } from "@/lib/chesterToast";
import { getErrorMessage } from "@/lib/errorMessage";
import { queryClient } from "@/lib/queryClient";
import { toolEnvelopeType, toolForEnvelopeType } from "@/lib/tools";

// Client-side guard against pathological files stalling file.text()/JSON.parse.
const MAX_BYTES = 50 * 1024 * 1024;

interface ParsedEnvelope {
  type?: string;
  kind?: string;
  title?: string;
  name?: string;
  document_type?: string;
  schema_version?: number;
}

export interface EnvelopeImportDialogProps {
  /** The tool whose list page opened this dialog — the file's envelope type
   * must match, and the initiative picker is scoped to this tool's create
   * permission. */
  tool: Tool;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** When set (inside an initiative tab), the target is fixed and the picker
   * is hidden. */
  fixedInitiativeId?: number;
  onImported?: () => void;
}

/** Generic single-envelope import — the file's ``type`` selects the backend
 * importer; this dialog validates it matches ``tool``, previews it, and posts
 * to /imports/envelope. Generalizes the old ProjectImportDialog for every
 * importable tool. */
export function EnvelopeImportDialog({
  tool,
  open,
  onOpenChange,
  fixedInitiativeId,
  onImported,
}: EnvelopeImportDialogProps) {
  const { t } = useTranslation(["imports", "common"]);
  const guildId = useActiveGuildId();
  const initiativesQuery = useInitiatives();
  const { filterVisible, permissionsFor } = useInitiativeAccess();

  const [envelope, setEnvelope] = useState<ParsedEnvelope | null>(null);
  const [parseError, setParseError] = useState<string | null>(null);
  const [initiativeId, setInitiativeId] = useState<string | null>(
    fixedInitiativeId != null ? String(fixedInitiativeId) : null
  );
  const [fileName, setFileName] = useState("");
  // Bumped on each file pick; an async read that finishes after a newer pick
  // started must not stamp its (stale) result onto the input.
  const readGeneration = useRef(0);

  const importMutation = useImportEnvelopeApiV1GGuildIdImportsEnvelopePost();

  const creatableInitiatives = useMemo(() => {
    if (fixedInitiativeId != null || !initiativesQuery.data) {
      return [];
    }
    return filterVisible(initiativesQuery.data).filter(
      (initiative) => permissionsFor(initiative)[tool].create
    );
  }, [fixedInitiativeId, initiativesQuery.data, filterVisible, permissionsFor, tool]);

  useEffect(() => {
    if (open) {
      setInitiativeId(
        fixedInitiativeId != null
          ? String(fixedInitiativeId)
          : creatableInitiatives.length === 1
            ? String(creatableInitiatives[0].id)
            : null
      );
    } else {
      setEnvelope(null);
      setParseError(null);
      setFileName("");
    }
  }, [open, fixedInitiativeId, creatableInitiatives]);

  const handleFileChange = async (e: ChangeEvent<HTMLInputElement>) => {
    const generation = ++readGeneration.current;
    // Only write state if this is still the most recent pick — a slower read
    // of an earlier file must not clobber a newer selection's result.
    const isStale = () => generation !== readGeneration.current;
    setParseError(null);
    setEnvelope(null);
    const file = e.target.files?.[0];
    if (!file) {
      setFileName("");
      return;
    }
    if (file.size > MAX_BYTES) {
      setFileName(file.name);
      setParseError(t("imports:envelope.fileTooLarge"));
      return;
    }
    setFileName(file.name);
    try {
      const text = await file.text();
      if (isStale()) {
        return;
      }
      const parsed = JSON.parse(text) as ParsedEnvelope;
      const type = parsed.type ?? parsed.kind;
      if (!type) {
        setParseError(t("imports:envelope.parseError"));
        return;
      }
      const fileTool = toolForEnvelopeType(type);
      if (fileTool == null) {
        setParseError(t("imports:envelope.parseError"));
        return;
      }
      if (fileTool !== tool) {
        // Right kind of file, wrong tool page — point the user at the right one.
        setParseError(t("imports:envelope.wrongTool", { type: fileTool }));
        return;
      }
      setEnvelope(parsed);
    } catch {
      if (isStale()) {
        return;
      }
      setParseError(t("imports:envelope.parseError"));
    }
  };

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    if (!envelope || !initiativeId) {
      return;
    }
    try {
      const response = (await importMutation.mutateAsync({
        guildId,
        data: {
          envelope: envelope as unknown as Record<string, unknown>,
          initiative_id: Number(initiativeId),
        },
      })) as
        | { result: { entity_title: string; unmatched_emails: string[] } }
        | { id: number; status: string };
      if ("result" in response) {
        toast.success(t("imports:envelope.success", { name: response.result.entity_title }));
        if (response.result.unmatched_emails.length > 0) {
          toast.warning(
            t("imports:envelope.warningUnmatched", {
              count: response.result.unmatched_emails.length,
              emails: response.result.unmatched_emails.join(", "),
            })
          );
        }
      } else {
        toast.success(t("imports:envelope.queued"));
      }
      // Refresh the tool's list (prefix invalidation catches all consumers).
      void queryClient.invalidateQueries({ queryKey: [tool] });
      onOpenChange(false);
      onImported?.();
    } catch (err) {
      toast.error(getErrorMessage(err, "imports:envelope.error"));
    }
  };

  const isSubmitting = importMutation.isPending;
  const canSubmit = !!envelope && !!initiativeId && !isSubmitting;
  const envelopeTitle = envelope?.title ?? envelope?.name ?? "";

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t("imports:envelope.title")}</DialogTitle>
          <DialogDescription>{t("imports:envelope.description")}</DialogDescription>
        </DialogHeader>
        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="envelope-import-file">{t("imports:envelope.selectFile")}</Label>
            <input
              id="envelope-import-file"
              type="file"
              accept=".json,application/json"
              onChange={handleFileChange}
              className="block w-full text-sm"
            />
            {fileName && !parseError ? (
              <p className="text-muted-foreground text-xs">{fileName}</p>
            ) : null}
            {parseError ? <p className="text-destructive text-sm">{parseError}</p> : null}
          </div>

          {envelope ? (
            <div className="rounded-md bg-muted p-3 text-sm">
              {t("imports:envelope.preview", {
                title: envelopeTitle,
                type: toolEnvelopeType(tool),
              })}
            </div>
          ) : null}

          {fixedInitiativeId == null && (
            <div className="space-y-2">
              <Label htmlFor="envelope-import-initiative">
                {t("imports:envelope.targetInitiative")}
              </Label>
              <Select
                value={initiativeId ?? undefined}
                onValueChange={(value) => setInitiativeId(value)}
              >
                <SelectTrigger id="envelope-import-initiative">
                  <SelectValue placeholder={t("imports:envelope.selectInitiative")} />
                </SelectTrigger>
                <SelectContent>
                  {creatableInitiatives.map((init) => (
                    <SelectItem key={init.id} value={String(init.id)}>
                      {init.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          )}

          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              onClick={() => onOpenChange(false)}
              disabled={isSubmitting}
            >
              {t("common:cancel")}
            </Button>
            <Button type="submit" disabled={!canSubmit}>
              {isSubmitting ? t("imports:envelope.importing") : t("imports:envelope.importButton")}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
