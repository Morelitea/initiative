import { useCallback, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { Plus } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  Command,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
  CommandSeparator,
} from "@/components/ui/command";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Select, SelectContent, SelectItem, SelectTrigger } from "@/components/ui/select";
import { useCreateProperty, useProperties } from "@/hooks/useProperties";
import {
  PropertyAppliesTo,
  PropertyType,
  type PropertyDefinitionCreate,
  type PropertyDefinitionRead,
  type PropertyOption,
  type PropertyType as PropertyTypeValue,
} from "@/api/generated/initiativeAPI.schemas";
import type { PropertyEntityKind } from "./PropertyList";
import { iconForPropertyType } from "./propertyTypeIcons";
import { slugify, typeRequiresOptions } from "./propertyHelpers";

export interface AddPropertyButtonProps {
  entityKind: PropertyEntityKind;
  currentPropertyIds: number[];
  onAdd: (definition: PropertyDefinitionRead) => void;
  disabled?: boolean;
}

const ORDERED_TYPES: PropertyTypeValue[] = [
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

export const AddPropertyButton = ({
  entityKind,
  currentPropertyIds,
  onAdd,
  disabled = false,
}: AddPropertyButtonProps) => {
  const { t } = useTranslation(["properties", "common"]);
  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState("");

  // Inline "create new property" form state.
  const [isCreating, setIsCreating] = useState(false);
  const [newName, setNewName] = useState("");
  const [newType, setNewType] = useState<PropertyTypeValue>(PropertyType.text);
  const [newOptions, setNewOptions] = useState<PropertyOption[]>([]);

  const propertiesQuery = useProperties();
  const createPropertyMutation = useCreateProperty();

  const currentIdSet = useMemo(() => new Set(currentPropertyIds), [currentPropertyIds]);

  const candidates = useMemo(() => {
    const all = propertiesQuery.data ?? [];
    return all.filter((definition) => {
      if (currentIdSet.has(definition.id)) return false;
      const appliesTo = definition.applies_to;
      return appliesTo === entityKind || appliesTo === PropertyAppliesTo.both;
    });
  }, [propertiesQuery.data, currentIdSet, entityKind]);

  const filteredCandidates = useMemo(() => {
    const term = search.trim().toLowerCase();
    if (!term) return candidates;
    return candidates.filter((definition) => definition.name.toLowerCase().includes(term));
  }, [candidates, search]);

  const resetCreateForm = useCallback(() => {
    setIsCreating(false);
    setNewName("");
    setNewType(PropertyType.text);
    setNewOptions([]);
  }, []);

  const handleOpenChange = useCallback(
    (next: boolean) => {
      setOpen(next);
      if (!next) {
        setSearch("");
        resetCreateForm();
      }
    },
    [resetCreateForm]
  );

  const startCreating = useCallback(() => {
    setNewName(search.trim());
    setNewType(PropertyType.text);
    setNewOptions([]);
    setIsCreating(true);
  }, [search]);

  const handleAddOption = useCallback(() => {
    setNewOptions((prev) => [...prev, { value: "", label: "" }]);
  }, []);

  const handleOptionChange = useCallback((index: number, patch: Partial<PropertyOption>) => {
    setNewOptions((prev) =>
      prev.map((option, i) => (i === index ? { ...option, ...patch } : option))
    );
  }, []);

  const handleOptionRemove = useCallback((index: number) => {
    setNewOptions((prev) => prev.filter((_, i) => i !== index));
  }, []);

  const handleCreate = useCallback(async () => {
    const name = newName.trim();
    if (!name) return;

    let options: PropertyOption[] | undefined;
    if (typeRequiresOptions(newType)) {
      options = newOptions
        .map((option) => ({
          value: option.value.trim() || slugify(option.label),
          label: option.label.trim() || option.value.trim(),
          color: option.color ?? null,
        }))
        .filter((option) => option.value !== "" && option.label !== "");

      if (options.length === 0) {
        return;
      }
    }

    const payload: PropertyDefinitionCreate = {
      name,
      type: newType,
      applies_to: PropertyAppliesTo.both,
      options,
    };

    try {
      const created = await createPropertyMutation.mutateAsync(payload);
      onAdd(created);
      handleOpenChange(false);
    } catch {
      // toast handled inside the mutation hook
    }
  }, [newName, newType, newOptions, createPropertyMutation, onAdd, handleOpenChange]);

  const canSubmit = useMemo(() => {
    if (!newName.trim()) return false;
    if (typeRequiresOptions(newType)) {
      return newOptions.some((option) => option.value.trim() || option.label.trim());
    }
    return true;
  }, [newName, newType, newOptions]);

  return (
    <Popover open={open} onOpenChange={handleOpenChange}>
      <PopoverTrigger asChild>
        <Button
          type="button"
          variant="ghost"
          size="sm"
          className="text-muted-foreground hover:text-foreground w-full justify-start"
          disabled={disabled}
        >
          <Plus className="mr-1 h-4 w-4" />
          {t("properties:addProperty")}
        </Button>
      </PopoverTrigger>
      <PopoverContent className="w-80 p-0" align="start">
        {isCreating ? (
          <div className="space-y-3 p-3">
            <div className="text-sm font-medium">{t("properties:picker.createHeading")}</div>
            <div className="space-y-2">
              <Label htmlFor="property-new-name" className="text-xs font-normal">
                {t("properties:picker.namePlaceholder")}
              </Label>
              <Input
                id="property-new-name"
                value={newName}
                onChange={(e) => setNewName(e.target.value)}
                placeholder={t("properties:picker.namePlaceholder")}
                autoFocus
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="property-new-type" className="text-xs font-normal">
                {t("properties:picker.typeLabel")}
              </Label>
              <Select
                value={newType}
                onValueChange={(value) => {
                  const nextType = value as PropertyTypeValue;
                  setNewType(nextType);
                  if (!typeRequiresOptions(nextType)) {
                    setNewOptions([]);
                  } else if (newOptions.length === 0) {
                    setNewOptions([{ value: "", label: "" }]);
                  }
                }}
              >
                <SelectTrigger id="property-new-type">
                  <div className="flex min-w-0 items-center gap-2">
                    {(() => {
                      const Icon = iconForPropertyType(newType);
                      return <Icon className="h-4 w-4 shrink-0" />;
                    })()}
                    <span className="truncate">{t(`properties:types.${newType}`)}</span>
                  </div>
                </SelectTrigger>
                <SelectContent>
                  {ORDERED_TYPES.map((typeValue) => {
                    const Icon = iconForPropertyType(typeValue);
                    const label = t(`properties:types.${typeValue}`);
                    return (
                      <SelectItem key={typeValue} value={typeValue} textValue={label}>
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

            {typeRequiresOptions(newType) ? (
              <div className="space-y-2">
                <Label className="text-xs font-normal">
                  {t("properties:manager.optionsLabel")}
                </Label>
                <ul className="space-y-2">
                  {newOptions.map((option, index) => (
                    <li key={index} className="flex items-center gap-2">
                      <Input
                        value={option.value}
                        onChange={(e) => handleOptionChange(index, { value: e.target.value })}
                        placeholder={t("properties:picker.optionValuePlaceholder")}
                        className="h-8 flex-1"
                      />
                      <Input
                        value={option.label}
                        onChange={(e) => handleOptionChange(index, { label: e.target.value })}
                        placeholder={t("properties:picker.optionLabelPlaceholder")}
                        className="h-8 flex-1"
                      />
                      <Button
                        type="button"
                        variant="ghost"
                        size="icon-sm"
                        onClick={() => handleOptionRemove(index)}
                        aria-label={t("properties:picker.removeOption")}
                      >
                        <Plus className="h-4 w-4 rotate-45" />
                      </Button>
                    </li>
                  ))}
                </ul>
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  className="w-full"
                  onClick={handleAddOption}
                >
                  <Plus className="mr-1 h-4 w-4" />
                  {t("properties:picker.addOption")}
                </Button>
              </div>
            ) : null}

            <div className="flex gap-2">
              <Button
                type="button"
                size="sm"
                className="flex-1"
                onClick={() => void handleCreate()}
                disabled={!canSubmit || createPropertyMutation.isPending}
              >
                {t("properties:picker.createButton")}
              </Button>
              <Button type="button" size="sm" variant="outline" onClick={() => resetCreateForm()}>
                {t("common:cancel")}
              </Button>
            </div>
          </div>
        ) : (
          <Command shouldFilter={false}>
            <CommandInput
              placeholder={t("properties:picker.placeholder")}
              value={search}
              onValueChange={setSearch}
            />
            <CommandList>
              {propertiesQuery.isLoading ? (
                <div className="text-muted-foreground py-6 text-center text-sm">
                  {t("common:loading")}
                </div>
              ) : (
                <>
                  {filteredCandidates.length === 0 ? (
                    <div className="text-muted-foreground py-6 text-center text-sm">
                      {t("properties:picker.empty")}
                    </div>
                  ) : (
                    <CommandGroup>
                      {filteredCandidates.map((definition) => {
                        const Icon = iconForPropertyType(definition.type);
                        return (
                          <CommandItem
                            key={definition.id}
                            value={`property-${definition.id}`}
                            onSelect={() => {
                              onAdd(definition);
                              handleOpenChange(false);
                            }}
                            className="cursor-pointer"
                          >
                            <Icon className="text-muted-foreground mr-2 h-4 w-4 shrink-0" />
                            <div className="flex flex-col">
                              <span>{definition.name}</span>
                              <span className="text-muted-foreground text-xs">
                                {t(`properties:types.${definition.type}`)}
                              </span>
                            </div>
                          </CommandItem>
                        );
                      })}
                    </CommandGroup>
                  )}
                  <CommandSeparator />
                  <CommandGroup>
                    <CommandItem
                      key="create-new"
                      value="create-new"
                      onSelect={startCreating}
                      className="cursor-pointer"
                    >
                      <Plus className="mr-2 h-4 w-4" />
                      {t("properties:picker.createHeading")}
                    </CommandItem>
                  </CommandGroup>
                </>
              )}
            </CommandList>
          </Command>
        )}
      </PopoverContent>
    </Popover>
  );
};
