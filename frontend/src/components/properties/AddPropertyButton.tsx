import { Plus } from "lucide-react";
import { useCallback, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import {
  type PropertyDefinitionCreate,
  type PropertyDefinitionRead,
  type PropertyOption,
  PropertyType,
  type PropertyType as PropertyTypeValue,
} from "@/api/generated/initiativeAPI.schemas";
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

import { normalizeOptionList, typeRequiresOptions } from "./propertyHelpers";
import { iconForPropertyType } from "./propertyTypeIcons";

export interface AddPropertyButtonProps {
  /**
   * Initiative the entity belongs to. Scopes both the candidate list (so the
   * picker only surfaces definitions from this initiative) and the inline
   * "create new property" submission (bakes ``initiative_id`` into the create
   * payload).
   */
  initiativeId: number;
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
  initiativeId,
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

  const propertiesQuery = useProperties({ initiativeId });
  const createPropertyMutation = useCreateProperty();

  const currentIdSet = useMemo(() => new Set(currentPropertyIds), [currentPropertyIds]);

  const candidates = useMemo(() => {
    const all = propertiesQuery.data ?? [];
    return all.filter((definition) => !currentIdSet.has(definition.id));
  }, [propertiesQuery.data, currentIdSet]);

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
      options = normalizeOptionList(newOptions);

      if (options.length === 0) {
        return;
      }
    }

    const payload: PropertyDefinitionCreate = {
      name,
      type: newType,
      initiative_id: initiativeId,
      options,
    };

    try {
      const created = await createPropertyMutation.mutateAsync(payload);
      onAdd(created);
      handleOpenChange(false);
    } catch {
      // toast handled inside the mutation hook
    }
  }, [newName, newType, newOptions, initiativeId, createPropertyMutation, onAdd, handleOpenChange]);

  const canSubmit = useMemo(() => {
    if (!newName.trim()) return false;
    if (typeRequiresOptions(newType)) {
      return normalizeOptionList(newOptions).length > 0;
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
          className="w-full justify-start text-muted-foreground hover:text-foreground"
          disabled={disabled}
        >
          <Plus className="mr-1 h-4 w-4" />
          {t("properties:addProperty")}
        </Button>
      </PopoverTrigger>
      <PopoverContent className="w-80 p-0" align="start">
        {isCreating ? (
          <div className="space-y-3 p-3">
            <div className="font-medium text-sm">{t("properties:picker.createHeading")}</div>
            <div className="space-y-2">
              <Label htmlFor="property-new-name" className="font-normal text-xs">
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
              <Label htmlFor="property-new-type" className="font-normal text-xs">
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
                <Label className="font-normal text-xs">
                  {t("properties:manager.optionsLabel")}
                </Label>
                <ul className="space-y-2">
                  {newOptions.map((option, index) => (
                    // Key by index, not by the edited field: keying on
                    // ``option.value``/``label`` remounts the input on every
                    // keystroke and steals focus. Inputs are controlled and
                    // rows only change via add/remove, so the index is correct.
                    // biome-ignore lint/suspicious/noArrayIndexKey: controlled rows with no stable id; keying on the edited field steals focus
                    <li key={index} className="flex items-center gap-2">
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
                <div className="py-6 text-center text-muted-foreground text-sm">
                  {t("common:loading")}
                </div>
              ) : (
                <>
                  {filteredCandidates.length === 0 ? (
                    <div className="py-6 text-center text-muted-foreground text-sm">
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
                            <Icon className="mr-2 h-4 w-4 shrink-0 text-muted-foreground" />
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
