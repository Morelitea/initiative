import { Loader2 } from "lucide-react";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import type { CalendarRead, ResourceGrantSchema } from "@/api/generated/initiativeAPI.schemas";
import { Tool } from "@/api/generated/initiativeAPI.schemas";
import { CreateAccessSection } from "@/components/access/CreateAccessSection";
import { DEFAULT_GRANTS } from "@/components/access/grants";
import { Button } from "@/components/ui/button";
import { ColorPickerPopover } from "@/components/ui/color-picker-popover";
import {
  Dialog,
  DialogContent,
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
import { useCreateCalendar } from "@/hooks/useCalendars";
import { useToolCreateAccess } from "@/hooks/useInitiativeAccess";
import type { DialogProps } from "@/types/dialog";

const DEFAULT_COLOR = "#6366f1";

type CreateCalendarDialogProps = DialogProps & {
  /** If provided, the initiative is locked and the picker is hidden. */
  initiativeId?: number;
  /** If provided, pre-selects this initiative (but the user can change it). */
  defaultInitiativeId?: number;
  onSuccess?: (calendar: CalendarRead) => void;
};

export const CreateCalendarDialog = ({
  open,
  onOpenChange,
  initiativeId,
  defaultInitiativeId,
  onSuccess,
}: CreateCalendarDialogProps) => {
  const { t } = useTranslation(["calendars", "common"]);

  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [color, setColor] = useState(DEFAULT_COLOR);
  const [grants, setGrants] = useState<ResourceGrantSchema[]>([...DEFAULT_GRANTS]);
  const [selectedInitiativeId, setSelectedInitiativeId] = useState(
    defaultInitiativeId ? String(defaultInitiativeId) : ""
  );

  // Initiatives the current user may create calendars in — backs the picker
  // shown when no initiative is locked.
  const { creatableInitiatives } = useToolCreateAccess(Tool.calendar, { enabled: open });

  const effectiveInitiativeId =
    initiativeId ?? (selectedInitiativeId ? Number(selectedInitiativeId) : null);

  useEffect(() => {
    if (open) {
      if (defaultInitiativeId) {
        setSelectedInitiativeId(String(defaultInitiativeId));
      } else if (creatableInitiatives.length === 1) {
        setSelectedInitiativeId(String(creatableInitiatives[0].id));
      }
    } else {
      setName("");
      setDescription("");
      setColor(DEFAULT_COLOR);
      setGrants([...DEFAULT_GRANTS]);
      setSelectedInitiativeId(defaultInitiativeId ? String(defaultInitiativeId) : "");
    }
  }, [open, defaultInitiativeId, creatableInitiatives]);

  const createCalendar = useCreateCalendar({
    onSuccess: (calendar) => {
      onOpenChange(false);
      onSuccess?.(calendar);
    },
  });

  const isCreating = createCalendar.isPending;
  const canSubmit = name.trim() && !!effectiveInitiativeId && !isCreating;

  const handleSubmit = () => {
    const trimmedName = name.trim();
    if (!trimmedName || !effectiveInitiativeId) return;
    createCalendar.mutate({
      name: trimmedName,
      description: description.trim() || undefined,
      color,
      initiative_id: effectiveInitiativeId,
      grants,
    });
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[90vh] w-full max-w-lg overflow-y-auto rounded-2xl border bg-card shadow-2xl">
        <DialogHeader>
          <DialogTitle>{t("createCalendar")}</DialogTitle>
        </DialogHeader>

        <div className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="create-calendar-name">{t("calendarName")}</Label>
            <Input
              id="create-calendar-name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder={t("calendarNamePlaceholder")}
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
            <Label htmlFor="create-calendar-description">{t("description")}</Label>
            <Textarea
              id="create-calendar-description"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder={t("calendarDescriptionPlaceholder")}
              rows={2}
            />
          </div>

          <div className="space-y-2">
            <Label htmlFor="create-calendar-color">{t("calendarColor")}</Label>
            <ColorPickerPopover
              id="create-calendar-color"
              value={color}
              onChangeComplete={setColor}
              triggerLabel={t("calendarColor")}
            />
          </div>

          {initiativeId === undefined && (
            <div className="space-y-2">
              <Label htmlFor="create-calendar-initiative">{t("initiative")}</Label>
              <Select
                value={selectedInitiativeId}
                onValueChange={(value) => {
                  setSelectedInitiativeId(value);
                  // Access grants are initiative-scoped (member/role
                  // principals); a new target starts over with default access.
                  setGrants([...DEFAULT_GRANTS]);
                }}
              >
                <SelectTrigger id="create-calendar-initiative">
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
            </div>
          )}

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
              t("createCalendar")
            )}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
};
