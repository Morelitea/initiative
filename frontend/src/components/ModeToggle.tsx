import { Moon, Sun } from "lucide-react";
import { useTranslation } from "react-i18next";

import { useTheme } from "@/hooks/useTheme";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuTrigger,
  DropdownMenuLabel,
} from "@/components/ui/dropdown-menu";

export const ModeToggle = () => {
  const { theme, setTheme } = useTheme();
  const { t } = useTranslation("nav");

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button
          variant="ghost"
          size="icon"
          className="relative"
          type="button"
          aria-label={t("toggleTheme")}
        >
          <Sun className="h-5 w-5 scale-100 rotate-0 transition-all dark:scale-0 dark:-rotate-90" />
          <Moon className="absolute h-5 w-5 scale-0 rotate-90 transition-all dark:scale-100 dark:rotate-0" />
          <span className="sr-only">{t("toggleTheme")}</span>
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-36">
        <DropdownMenuLabel>{t("theme")}</DropdownMenuLabel>
        <DropdownMenuRadioGroup
          value={theme}
          onValueChange={(value) => setTheme(value as "light" | "dark" | "system")}
        >
          <DropdownMenuRadioItem value="system">{t("themeSystem")}</DropdownMenuRadioItem>
          <DropdownMenuRadioItem value="light">{t("themeLight")}</DropdownMenuRadioItem>
          <DropdownMenuRadioItem value="dark">{t("themeDark")}</DropdownMenuRadioItem>
        </DropdownMenuRadioGroup>
      </DropdownMenuContent>
    </DropdownMenu>
  );
};
