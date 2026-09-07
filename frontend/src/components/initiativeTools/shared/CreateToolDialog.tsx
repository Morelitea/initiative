import type { FlatNamespace } from "i18next";
import { Loader2 } from "lucide-react";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import type { ResourceGrantSchema, Tool } from "@/api/generated/initiativeAPI.schemas";
import { CreateAccessSection } from "@/components/access/CreateAccessSection";
import { DEFAULT_GRANTS } from "@/components/access/grants";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { useToolCreateAccess } from "@/hooks/useInitiativeAccess";
import { useInitiatives } from "@/hooks/useInitiatives";
import type { DialogProps } from "@/types/dialog";
import type { TranslateFn } from "@/types/i18n";
import type { MutationOpts } from "@/types/mutation";

/**
 * The create payload shared by the simple initiative-tool create dialogs. Both
 * `QueueCreate` and `CounterGroupCreate` are structurally this shape, so the
 * dialog can build the payload once and hand it to either mutation hook.
 */
export type ToolCreatePayload = {
  name: string;
  description?: string | null;
  initiative_id: number;
  grants?: ResourceGrantSchema[];
};

/**
 * The small, concrete bundle that distinguishes one tool's create dialog from
 * another: its i18n namespace/keys, element-id prefix, and create-mutation hook.
 */
export interface CreateToolConfig<TRead> {
  /** The tool being created — drives the picker's creatable-initiative filter. */
  tool: Tool;
  /** i18n namespace for this tool's strings (e.g. "queues"). */
  namespace: FlatNamespace;
  /** Key for the dialog title and the submit button label. */
  titleKey: string;
  /** Key for the dialog description. */
  descriptionKey: string;
  /** Prefix for field element ids, e.g. "create-queue" → "create-queue-name". */
  idPrefix: string;
  /** The domain create-mutation hook (e.g. `useCreateQueue`). */
  useCreate: (options: MutationOpts<TRead, ToolCreatePayload>) => {
    mutate: (payload: ToolCreatePayload) => void;
    isPending: boolean;
  };
}

export type CreateToolDialogProps<TRead> = DialogProps & {
  /** If provided, the initiative is locked and cannot be changed. */
  initiativeId?: number;
  /** If provided, pre-selects this initiative (but the user can change it). */
  defaultInitiativeId?: number;
  /** Called after successful creation. */
  onSuccess?: (result: TRead) => void;
  config: CreateToolConfig<TRead>;
};

/**
 * Shared implementation behind the queue and counter-group create dialogs,
 * which were line-for-line twins apart from their i18n keys, element ids, and
 * create-mutation hook. Each tool keeps a thin named wrapper with an unchanged
 * public signature.
 */
export const CreateToolDialog = <TRead,>({
  open,
  onOpenChange,
  initiativeId,
  defaultInitiativeId,
  onSuccess,
  config,
}: CreateToolDialogProps<TRead>) => {
  const { tool, namespace, titleKey, descriptionKey, idPrefix, useCreate } = config;
  // The namespace and several keys are supplied by config (dynamic per tool), so
  // use the loose translation signature rather than the statically-typed keys.
  const { t: translate } = useTranslation(namespace);
  const t = translate as TranslateFn;

  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [selectedInitiativeId, setSelectedInitiativeId] = useState(
    defaultInitiativeId ? String(defaultInitiativeId) : ""
  );
  const [grants, setGrants] = useState<ResourceGrantSchema[]>([...DEFAULT_GRANTS]);

  const initiativesQuery = useInitiatives();
  const initiatives = initiativesQuery.data ?? [];

  // The picker only offers initiatives the user may actually create this tool
  // in (server-computed create flags; folds in the tool's master switch).
  const { creatableInitiatives } = useToolCreateAccess(tool);

  const effectiveInitiativeId =
    initiativeId ?? (selectedInitiativeId ? Number(selectedInitiativeId) : null);

  const lockedInitiative = initiativeId
    ? (initiatives.find((i) => i.id === initiativeId) ?? null)
    : null;

  // Reset form when dialog closes, set default initiative when dialog opens
  useEffect(() => {
    if (open) {
      if (defaultInitiativeId) {
        setSelectedInitiativeId(String(defaultInitiativeId));
      }
    } else {
      setName("");
      setDescription("");
      setSelectedInitiativeId(defaultInitiativeId ? String(defaultInitiativeId) : "");
      setGrants([...DEFAULT_GRANTS]);
    }
  }, [open, defaultInitiativeId]);

  const createTool = useCreate({
    onSuccess: (result) => {
      onOpenChange(false);
      onSuccess?.(result);
    },
  });

  const isCreating = createTool.isPending;
  const canSubmit = !!name.trim() && !!effectiveInitiativeId && !isCreating;

  const handleSubmit = () => {
    const trimmedName = name.trim();
    if (!trimmedName || !effectiveInitiativeId) return;
    createTool.mutate({
      name: trimmedName,
      description: description.trim() || undefined,
      initiative_id: effectiveInitiativeId,
      grants,
    });
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-screen w-full overflow-y-auto rounded-2xl border bg-card shadow-2xl sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>{t(titleKey)}</DialogTitle>
          <DialogDescription>{t(descriptionKey)}</DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor={`${idPrefix}-name`}>{t("name")}</Label>
            <Input
              id={`${idPrefix}-name`}
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder={t("namePlaceholder")}
              onKeyDown={(e) => {
                if (e.key === "Enter" && canSubmit) {
                  e.preventDefault();
                  handleSubmit();
                }
              }}
              autoFocus
            />
          </div>

          <div className="space-y-2">
            <Label htmlFor={`${idPrefix}-description`}>{t("description")}</Label>
            <Textarea
              id={`${idPrefix}-description`}
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder={t("descriptionPlaceholder")}
              rows={3}
            />
          </div>

          <div className="space-y-2">
            <Label htmlFor={`${idPrefix}-initiative`}>{t("initiative")}</Label>
            {initiativeId ? (
              <div className="rounded-md border px-3 py-2 text-sm">
                {lockedInitiative?.name ?? t("selectInitiative")}
              </div>
            ) : (
              <Select
                value={selectedInitiativeId}
                onValueChange={(value) => {
                  setSelectedInitiativeId(value);
                  // Access grants are initiative-scoped; a new target starts
                  // over with default access.
                  setGrants([...DEFAULT_GRANTS]);
                }}
              >
                <SelectTrigger id={`${idPrefix}-initiative`}>
                  <SelectValue placeholder={t("selectInitiative")} />
                </SelectTrigger>
                <SelectContent>
                  {creatableInitiatives.map((initiative) => (
                    <SelectItem key={initiative.id} value={String(initiative.id)}>
                      {initiative.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            )}
          </div>

          <CreateAccessSection
            initiativeId={effectiveInitiativeId}
            grants={grants}
            onChange={setGrants}
          />
        </div>

        <DialogFooter>
          <Button type="button" onClick={handleSubmit} disabled={!canSubmit}>
            {isCreating ? (
              <>
                <Loader2 className="h-4 w-4 animate-spin" />
                {t("creating")}
              </>
            ) : (
              t(titleKey)
            )}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
};
