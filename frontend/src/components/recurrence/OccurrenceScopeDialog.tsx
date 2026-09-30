import { type ReactNode, useCallback, useState } from "react";
import { useTranslation } from "react-i18next";

import type { CalendarEventUpdateScope } from "@/api/generated/initiativeAPI.schemas";
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
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";

export type OccurrenceScope = NonNullable<CalendarEventUpdateScope>;

/** What the change is: it names the dialog and its button. */
export type ScopeAction = "edit" | "delete" | "answer";

const ALL_SCOPES: OccurrenceScope[] = ["this", "following", "all"];

type OccurrenceScopeDialogProps = {
  action: ScopeAction;
  /** The scopes this change offers: an answer has no "from here on". */
  scopes: OccurrenceScope[];
  onChoose: (scope: OccurrenceScope | null) => void;
};

/** Which occurrences of a repeating event a change is for. */
export const OccurrenceScopeDialog = ({ action, scopes, onChoose }: OccurrenceScopeDialogProps) => {
  const { t } = useTranslation(["calendars", "common"]);
  const [scope, setScope] = useState<OccurrenceScope>("this");
  return (
    <Dialog open onOpenChange={(open) => !open && onChoose(null)}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>{t(`scope.title.${action}`)}</DialogTitle>
          <DialogDescription>{t("scope.description")}</DialogDescription>
        </DialogHeader>
        <RadioGroup value={scope} onValueChange={(value) => setScope(value as OccurrenceScope)}>
          {scopes.map((option) => (
            <div key={option} className="flex items-center gap-3">
              <RadioGroupItem value={option} id={`occurrence-scope-${option}`} />
              <Label htmlFor={`occurrence-scope-${option}`} className="cursor-pointer">
                {t(`scope.${option}`)}
              </Label>
            </div>
          ))}
        </RadioGroup>
        <DialogFooter>
          <Button variant="ghost" onClick={() => onChoose(null)}>
            {t("common:cancel")}
          </Button>
          <Button
            variant={action === "delete" ? "destructive" : "default"}
            onClick={() => onChoose(scope)}
          >
            {t(`scope.confirm.${action}`)}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
};

/**
 * Ask which occurrences a change is for, as a promise: the scope picked, or
 * `null` when the dialog was closed. Render `dialog` once in the page.
 */
export const useScopePrompt = (): {
  ask: (action: ScopeAction, scopes?: OccurrenceScope[]) => Promise<OccurrenceScope | null>;
  dialog: ReactNode;
} => {
  const [asking, setAsking] = useState<{
    action: ScopeAction;
    scopes: OccurrenceScope[];
    resolve: (scope: OccurrenceScope | null) => void;
  } | null>(null);
  const ask = useCallback(
    (action: ScopeAction, scopes: OccurrenceScope[] = ALL_SCOPES) =>
      new Promise<OccurrenceScope | null>((resolve) => setAsking({ action, scopes, resolve })),
    []
  );
  const dialog = asking ? (
    <OccurrenceScopeDialog
      action={asking.action}
      scopes={asking.scopes}
      onChoose={(scope) => {
        asking.resolve(scope);
        setAsking(null);
      }}
    />
  ) : null;
  return { ask, dialog };
};
