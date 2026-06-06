import { type FocusEvent, type KeyboardEvent, type RefObject, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { FormulaCellInput } from "@/components/documents/spreadsheet/FormulaCellInput";
import type { FormulaRefToken } from "@/lib/spreadsheet/formula-refs";

interface SpreadsheetFormulaBarProps {
  /** A1 reference of the active cell or range (``"B4"`` / ``"A1:C3"``) — the
   *  name box display. */
  selectionLabel: string;
  /** Go-to: navigate/select the cell or range the name box text names. */
  onNavigate: (text: string) => void;
  /** The active cell's raw text — its formula/value, or the live edit draft. */
  value: string;
  /** References in ``value`` while a formula is being edited (colors them). */
  tokens: FormulaRefToken[];
  /** Ref to the formula-bar ``<input>`` so the editor can drive point-mode
   *  reference insertion and caret restoration against it. */
  inputRef: RefObject<HTMLInputElement | null>;
  onChange: (value: string) => void;
  onFocus: () => void;
  onKeyDown: (e: KeyboardEvent<HTMLInputElement>) => void;
  onBlur: (e: FocusEvent<HTMLInputElement>) => void;
  readOnly: boolean;
}

/**
 * The formula bar above the grid: a name box (active-cell reference, editable
 * for go-to navigation) and an editable formula input that mirrors the active
 * cell. Both the in-cell editor and this bar drive the same edit draft, so a
 * formula can be typed or pointed-at from either surface (see the editor's
 * shared ``activeEditorRef`` / point-mode wiring).
 */
export const SpreadsheetFormulaBar = ({
  selectionLabel,
  onNavigate,
  value,
  tokens,
  inputRef,
  onChange,
  onFocus,
  onKeyDown,
  onBlur,
  readOnly,
}: SpreadsheetFormulaBarProps) => {
  const { t } = useTranslation(["documents", "common"]);
  // Local name-box draft, synced to the selection unless the user is editing it.
  const [nameDraft, setNameDraft] = useState(selectionLabel);
  const [nameFocused, setNameFocused] = useState(false);
  useEffect(() => {
    if (!nameFocused) setNameDraft(selectionLabel);
  }, [selectionLabel, nameFocused]);

  const handleNameKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter") {
      e.preventDefault();
      onNavigate(nameDraft);
      e.currentTarget.blur();
    } else if (e.key === "Escape") {
      e.preventDefault();
      setNameDraft(selectionLabel);
      e.currentTarget.blur();
    }
  };

  return (
    <div className="flex shrink-0 items-stretch border-border border-b bg-background text-sm">
      <input
        aria-label={t("documents:spreadsheet.formulaBar.nameBoxLabel")}
        title={t("documents:spreadsheet.formulaBar.nameBoxLabel")}
        className="w-24 shrink-0 border-border border-r bg-background px-2 py-1 text-center font-mono text-xs outline-none focus:bg-muted/40"
        value={nameDraft}
        spellCheck={false}
        onChange={(e) => setNameDraft(e.target.value)}
        onFocus={(e) => {
          setNameFocused(true);
          e.currentTarget.select();
        }}
        onBlur={() => {
          setNameFocused(false);
          setNameDraft(selectionLabel);
        }}
        onKeyDown={handleNameKeyDown}
      />
      <div
        aria-hidden
        className="flex shrink-0 select-none items-center border-border border-r px-2.5 font-serif text-muted-foreground italic"
      >
        fx
      </div>
      <div className="relative h-7 min-w-0 flex-1">
        {readOnly ? (
          <div className="flex h-full w-full items-center overflow-hidden whitespace-pre px-1.5 text-muted-foreground">
            {value}
          </div>
        ) : (
          <FormulaCellInput
            inputRef={inputRef}
            value={value}
            tokens={tokens}
            onChange={onChange}
            onFocus={onFocus}
            onKeyDown={onKeyDown}
            onBlur={onBlur}
          />
        )}
      </div>
    </div>
  );
};
