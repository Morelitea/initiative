import { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { useParams } from "@tanstack/react-router";
import { AlertCircle, Loader2, Pencil, Plus, Trash2, X } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { ColorPickerPopover } from "@/components/ui/color-picker-popover";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
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
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  useCreateProperty,
  useDeleteProperty,
  useProperties,
  useUpdateProperty,
} from "@/hooks/useProperties";
import {
  PropertyAppliesTo,
  PropertyType,
  type PropertyDefinitionCreate,
  type PropertyDefinitionRead,
  type PropertyDefinitionUpdate,
  type PropertyOption,
  type PropertyType as PropertyTypeValue,
} from "@/api/generated/initiativeAPI.schemas";
import { iconForPropertyType } from "@/components/properties/propertyTypeIcons";
import { slugify, typeRequiresOptions } from "@/components/properties/propertyHelpers";

const PROPERTY_TYPE_OPTIONS: PropertyTypeValue[] = [
  PropertyType.text,
  PropertyType.number,
  PropertyType.checkbox,
  PropertyType.date,
  PropertyType.datetime,
  PropertyType.url,
  PropertyType.select,
  PropertyType.multi_select,
  PropertyType.user_reference,
];

const APPLIES_TO_OPTIONS: PropertyAppliesTo[] = [
  PropertyAppliesTo.both,
  PropertyAppliesTo.document,
  PropertyAppliesTo.task,
];

const DEFAULT_COLOR = "#64748B";

interface DialogState {
  mode: "create" | "edit";
  definition?: PropertyDefinitionRead;
}

interface FormState {
  name: string;
  type: PropertyTypeValue;
  appliesTo: PropertyAppliesTo;
  color: string | null;
  options: PropertyOption[];
}

const emptyFormState: FormState = {
  name: "",
  type: PropertyType.text,
  appliesTo: PropertyAppliesTo.both,
  color: null,
  options: [],
};

const definitionToFormState = (definition: PropertyDefinitionRead): FormState => ({
  name: definition.name,
  type: definition.type,
  appliesTo: definition.applies_to,
  color: definition.color,
  options: (definition.options ?? []).map((option) => ({
    value: option.value,
    label: option.label,
    color: option.color ?? null,
  })),
});

/**
 * Sub-editor for select / multi_select option lists. Kept in-file because it
 * is only useful to the manager dialog — no other callers need it.
 */
interface OptionListEditorProps {
  options: PropertyOption[];
  onChange: (next: PropertyOption[]) => void;
  disabled?: boolean;
}

const OptionListEditor = ({ options, onChange, disabled }: OptionListEditorProps) => {
  const { t } = useTranslation(["properties", "common"]);

  const handleAdd = () => {
    onChange([...options, { value: "", label: "", color: null }]);
  };

  const handlePatch = (index: number, patch: Partial<PropertyOption>) => {
    onChange(options.map((option, i) => (i === index ? { ...option, ...patch } : option)));
  };

  const handleRemove = (index: number) => {
    onChange(options.filter((_, i) => i !== index));
  };

  return (
    <div className="space-y-2">
      {options.length === 0 ? (
        <p className="text-muted-foreground text-sm">{t("properties:picker.optionsRequired")}</p>
      ) : null}
      <ul className="space-y-2">
        {options.map((option, index) => (
          <li key={index} className="flex flex-wrap items-center gap-2 sm:flex-nowrap">
            <Input
              value={option.value}
              onChange={(e) =>
                handlePatch(index, {
                  value: e.target.value,
                })
              }
              onBlur={(e) => {
                // Auto-slugify the value when the user leaves the field so it
                // satisfies the backend pattern. Preserve the label verbatim.
                const raw = e.target.value;
                if (!raw) return;
                const slug = slugify(raw);
                if (slug && slug !== raw) {
                  handlePatch(index, { value: slug });
                }
              }}
              placeholder={t("properties:manager.optionValuePlaceholder")}
              className="h-9 flex-1"
              disabled={disabled}
            />
            <Input
              value={option.label}
              onChange={(e) => handlePatch(index, { label: e.target.value })}
              placeholder={t("properties:manager.optionLabelPlaceholder")}
              className="h-9 flex-1"
              disabled={disabled}
            />
            <div className="w-24">
              <ColorPickerPopover
                value={option.color ?? DEFAULT_COLOR}
                onChangeComplete={(value) => handlePatch(index, { color: value })}
                disabled={disabled}
                triggerLabel={t("properties:manager.colorLabel")}
                className="h-9"
              />
            </div>
            <Button
              type="button"
              variant="ghost"
              size="icon-sm"
              onClick={() => handleRemove(index)}
              aria-label={t("properties:manager.removeOption")}
              disabled={disabled}
            >
              <X className="h-4 w-4" />
            </Button>
          </li>
        ))}
      </ul>
      <Button type="button" variant="outline" size="sm" onClick={handleAdd} disabled={disabled}>
        <Plus className="mr-1 h-4 w-4" />
        {t("properties:manager.addOption")}
      </Button>
    </div>
  );
};

/**
 * Initiative-admin surface for listing and managing custom property
 * definitions. Pairs with ``PropertyFilter``/``PropertyList``/
 * ``PropertyInput`` which render individual values on documents and tasks.
 */
export const PropertyDefinitionManagerPage = () => {
  const { t } = useTranslation(["properties", "common"]);
  const params = useParams({ strict: false }) as { initiativeId?: string };
  const parsedInitiativeId = Number(params.initiativeId);
  const hasValidInitiativeId = Number.isFinite(parsedInitiativeId) && parsedInitiativeId > 0;
  const initiativeId = hasValidInitiativeId ? parsedInitiativeId : 0;

  const propertiesQuery = useProperties({
    initiativeId: hasValidInitiativeId ? initiativeId : undefined,
  });
  const createMutation = useCreateProperty();
  const updateMutation = useUpdateProperty();
  const deleteMutation = useDeleteProperty();

  const [dialogState, setDialogState] = useState<DialogState | null>(null);
  const [formState, setFormState] = useState<FormState>(emptyFormState);
  const [deleteTarget, setDeleteTarget] = useState<PropertyDefinitionRead | null>(null);

  const sortedDefinitions = useMemo(() => {
    const list = propertiesQuery.data ?? [];
    return [...list].sort((a, b) => {
      if (a.position !== b.position) return a.position - b.position;
      return a.name.localeCompare(b.name);
    });
  }, [propertiesQuery.data]);

  // Sync the form state when the dialog target changes. Using an effect
  // here (rather than initializing via state) avoids stale form data when
  // the user closes one edit dialog and opens another without remounting.
  useEffect(() => {
    if (!dialogState) {
      setFormState(emptyFormState);
      return;
    }
    if (dialogState.mode === "edit" && dialogState.definition) {
      setFormState(definitionToFormState(dialogState.definition));
    } else {
      setFormState(emptyFormState);
    }
  }, [dialogState]);

  const isEditing = dialogState?.mode === "edit";
  const submitting = createMutation.isPending || updateMutation.isPending;

  const handleOpenCreate = () => setDialogState({ mode: "create" });
  const handleOpenEdit = (definition: PropertyDefinitionRead) =>
    setDialogState({ mode: "edit", definition });
  const handleCloseDialog = () => setDialogState(null);

  const handleTypeChange = (nextType: PropertyTypeValue) => {
    setFormState((prev) => {
      // When switching into a select-style type, seed with a single empty
      // option so the editor renders a row to fill in. Switching away clears
      // any options so they don't silently linger on the payload.
      if (typeRequiresOptions(nextType) && prev.options.length === 0) {
        return { ...prev, type: nextType, options: [{ value: "", label: "", color: null }] };
      }
      if (!typeRequiresOptions(nextType)) {
        return { ...prev, type: nextType, options: [] };
      }
      return { ...prev, type: nextType };
    });
  };

  const normalizedOptions = useCallback((options: PropertyOption[]): PropertyOption[] => {
    return options
      .map((option) => ({
        value: option.value.trim() || slugify(option.label),
        label: option.label.trim() || option.value.trim(),
        color: option.color ?? null,
      }))
      .filter((option) => option.value !== "" && option.label !== "");
  }, []);

  const canSubmit = useMemo(() => {
    if (!formState.name.trim()) return false;
    if (typeRequiresOptions(formState.type)) {
      return normalizedOptions(formState.options).length > 0;
    }
    return true;
  }, [formState, normalizedOptions]);

  const handleSubmit = async () => {
    if (!canSubmit || !dialogState) return;

    const trimmedName = formState.name.trim();
    const options = typeRequiresOptions(formState.type)
      ? normalizedOptions(formState.options)
      : undefined;

    if (dialogState.mode === "create") {
      if (!hasValidInitiativeId) return;
      const payload: PropertyDefinitionCreate = {
        name: trimmedName,
        type: formState.type,
        applies_to: formState.appliesTo,
        initiative_id: initiativeId,
        color: formState.color ?? null,
        options,
      };
      try {
        await createMutation.mutateAsync(payload);
        toast.success(t("properties:manager.newDefinition"));
        handleCloseDialog();
      } catch {
        // Error toast handled by the mutation hook.
      }
      return;
    }

    if (!dialogState.definition) return;
    const payload: PropertyDefinitionUpdate = {
      name: trimmedName,
      applies_to: formState.appliesTo,
      color: formState.color ?? null,
      // Type is immutable on edit, so use the existing definition's type to
      // decide whether to include options in the PATCH payload.
      options: typeRequiresOptions(dialogState.definition.type) ? options : undefined,
    };
    try {
      const response = await updateMutation.mutateAsync({
        propertyId: dialogState.definition.id,
        data: payload,
      });
      if (response.orphaned_value_count > 0) {
        toast.warning(
          t("properties:manager.orphanedWarning", {
            count: response.orphaned_value_count,
          })
        );
      } else {
        toast.success(t("properties:manager.editDefinition"));
      }
      handleCloseDialog();
    } catch {
      // Error toast handled by the mutation hook.
    }
  };

  const handleConfirmDelete = async () => {
    if (!deleteTarget) return;
    try {
      await deleteMutation.mutateAsync(deleteTarget.id);
      toast.success(t("properties:manager.delete"));
      setDeleteTarget(null);
    } catch {
      // Error toast handled by the mutation hook.
    }
  };

  if (!hasValidInitiativeId) {
    return (
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <AlertCircle className="h-5 w-5" />
            {t("properties:manager.missingInitiative")}
          </CardTitle>
          <CardDescription>{t("properties:manager.missingInitiativeDescription")}</CardDescription>
        </CardHeader>
      </Card>
    );
  }

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader className="flex flex-row items-start justify-between gap-4">
          <div>
            <CardTitle>{t("properties:manager.title")}</CardTitle>
            <CardDescription>{t("properties:manager.description")}</CardDescription>
          </div>
          <Button onClick={handleOpenCreate}>
            <Plus className="mr-1 h-4 w-4" />
            {t("properties:manager.newDefinition")}
          </Button>
        </CardHeader>
        <CardContent>
          {propertiesQuery.isLoading ? (
            <div className="text-muted-foreground flex items-center gap-2 text-sm">
              <Loader2 className="h-4 w-4 animate-spin" />
              {t("common:loading")}
            </div>
          ) : sortedDefinitions.length === 0 ? (
            <p className="text-muted-foreground text-sm">{t("properties:noProperties")}</p>
          ) : (
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>{t("properties:manager.nameLabel")}</TableHead>
                    <TableHead>{t("properties:manager.typeLabel")}</TableHead>
                    <TableHead>{t("properties:manager.appliesToLabel")}</TableHead>
                    <TableHead>{t("properties:manager.optionsLabel")}</TableHead>
                    <TableHead>{t("properties:manager.colorLabel")}</TableHead>
                    <TableHead className="w-32 text-right" />
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {sortedDefinitions.map((definition) => {
                    const optionCount = definition.options?.length ?? 0;
                    return (
                      <TableRow key={definition.id}>
                        <TableCell className="font-medium">{definition.name}</TableCell>
                        <TableCell>
                          {(() => {
                            const Icon = iconForPropertyType(definition.type);
                            return (
                              <span className="inline-flex items-center gap-2">
                                <Icon className="text-muted-foreground h-4 w-4" aria-hidden />
                                <span>{t(`properties:types.${definition.type}`)}</span>
                              </span>
                            );
                          })()}
                        </TableCell>
                        <TableCell>{t(`properties:appliesTo.${definition.applies_to}`)}</TableCell>
                        <TableCell>{optionCount > 0 ? optionCount : "—"}</TableCell>
                        <TableCell>
                          {definition.color ? (
                            <span className="inline-flex items-center gap-2">
                              <span
                                aria-hidden
                                className="inline-block h-4 w-4 rounded-full border"
                                style={{ backgroundColor: definition.color }}
                              />
                              <span className="text-muted-foreground font-mono text-xs uppercase">
                                {definition.color}
                              </span>
                            </span>
                          ) : (
                            "—"
                          )}
                        </TableCell>
                        <TableCell className="text-right">
                          <div className="inline-flex items-center gap-1">
                            <Button
                              type="button"
                              variant="ghost"
                              size="icon-sm"
                              onClick={() => handleOpenEdit(definition)}
                              aria-label={t("properties:manager.editDefinition")}
                            >
                              <Pencil className="h-4 w-4" />
                            </Button>
                            <Button
                              type="button"
                              variant="ghost"
                              size="icon-sm"
                              onClick={() => setDeleteTarget(definition)}
                              aria-label={t("properties:manager.delete")}
                            >
                              <Trash2 className="h-4 w-4" />
                            </Button>
                          </div>
                        </TableCell>
                      </TableRow>
                    );
                  })}
                </TableBody>
              </Table>
            </div>
          )}
        </CardContent>
      </Card>

      <Dialog
        open={dialogState !== null}
        onOpenChange={(next) => {
          if (!next) handleCloseDialog();
        }}
      >
        <DialogContent className="sm:max-w-xl">
          <DialogHeader>
            <DialogTitle>
              {isEditing
                ? t("properties:manager.editDefinition")
                : t("properties:manager.newDefinition")}
            </DialogTitle>
            <DialogDescription>{t("properties:manager.description")}</DialogDescription>
          </DialogHeader>

          <div className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="property-manager-name">{t("properties:manager.nameLabel")}</Label>
              <Input
                id="property-manager-name"
                value={formState.name}
                onChange={(e) => setFormState((prev) => ({ ...prev, name: e.target.value }))}
                autoFocus
              />
            </div>

            <div className="grid gap-4 sm:grid-cols-2">
              <div className="space-y-2">
                <Label htmlFor="property-manager-type">{t("properties:manager.typeLabel")}</Label>
                <Select
                  value={formState.type}
                  onValueChange={(next) => handleTypeChange(next as PropertyTypeValue)}
                  disabled={isEditing}
                >
                  <SelectTrigger id="property-manager-type">
                    <div className="flex min-w-0 items-center gap-2">
                      {(() => {
                        const Icon = iconForPropertyType(formState.type);
                        return <Icon className="h-4 w-4 shrink-0" />;
                      })()}
                      <span className="truncate">{t(`properties:types.${formState.type}`)}</span>
                    </div>
                  </SelectTrigger>
                  <SelectContent>
                    {PROPERTY_TYPE_OPTIONS.map((type) => {
                      const Icon = iconForPropertyType(type);
                      const label = t(`properties:types.${type}`);
                      return (
                        <SelectItem key={type} value={type} textValue={label}>
                          <div className="flex items-center gap-2">
                            <Icon className="h-4 w-4 shrink-0" />
                            <span>{label}</span>
                          </div>
                        </SelectItem>
                      );
                    })}
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-2">
                <Label htmlFor="property-manager-applies-to">
                  {t("properties:manager.appliesToLabel")}
                </Label>
                <Select
                  value={formState.appliesTo}
                  onValueChange={(next) =>
                    setFormState((prev) => ({ ...prev, appliesTo: next as PropertyAppliesTo }))
                  }
                >
                  <SelectTrigger id="property-manager-applies-to">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {APPLIES_TO_OPTIONS.map((scope) => (
                      <SelectItem key={scope} value={scope}>
                        {t(`properties:appliesTo.${scope}`)}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            </div>

            <div className="space-y-2">
              <Label>{t("properties:manager.colorLabel")}</Label>
              <ColorPickerPopover
                value={formState.color ?? DEFAULT_COLOR}
                onChangeComplete={(value) => setFormState((prev) => ({ ...prev, color: value }))}
              />
            </div>

            {typeRequiresOptions(formState.type) ? (
              <div className="space-y-2">
                <Label>{t("properties:manager.optionsLabel")}</Label>
                <OptionListEditor
                  options={formState.options}
                  onChange={(next) => setFormState((prev) => ({ ...prev, options: next }))}
                />
              </div>
            ) : null}
          </div>

          <DialogFooter>
            <Button type="button" variant="outline" onClick={handleCloseDialog}>
              {t("common:cancel")}
            </Button>
            <Button
              type="button"
              onClick={() => void handleSubmit()}
              disabled={!canSubmit || submitting}
            >
              {submitting ? t("common:submitting") : t("common:save")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <ConfirmDialog
        open={deleteTarget !== null}
        onOpenChange={(next) => {
          if (!next) setDeleteTarget(null);
        }}
        title={t("properties:manager.deleteConfirmTitle")}
        description={t("properties:manager.deleteConfirmBody")}
        confirmLabel={t("properties:manager.delete")}
        cancelLabel={t("common:cancel")}
        onConfirm={() => void handleConfirmDelete()}
        isLoading={deleteMutation.isPending}
        destructive
      />
    </div>
  );
};
