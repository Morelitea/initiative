import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";

export interface EditorInsertMenuProps {
  insertOptions: Array<{ label: string; action: () => void; disabled?: boolean }>;
}

export const EditorInsertMenu = ({ insertOptions }: EditorInsertMenuProps) => {
  const { t } = useTranslation("documents");

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button type="button" variant="ghost">
          {t("editor.insert")}
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent className="w-48">
        <DropdownMenuLabel>{t("editor.insert")}</DropdownMenuLabel>
        <DropdownMenuSeparator />
        {insertOptions.map((item) => (
          <DropdownMenuItem
            key={item.label}
            disabled={item.disabled}
            onSelect={(event) => {
              event.preventDefault();
              item.action();
            }}
          >
            {item.label}
          </DropdownMenuItem>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  );
};
