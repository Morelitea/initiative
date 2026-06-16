import { Moon, Sun } from "lucide-react";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuLabel,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { type PridePreference, usePride } from "@/hooks/usePride";
import { useTheme } from "@/hooks/useTheme";

export const ModeToggle = () => {
  const { theme, setTheme } = useTheme();
  const { preference: pride, setPreference: setPride } = usePride();
  const { t } = useTranslation("nav");

  return (
    // modal={false}: a modal dropdown nested in the non-modal mobile sidebar
    // drawer dismisses the drawer on open (see SidebarUserFooter).
    <DropdownMenu modal={false}>
      <DropdownMenuTrigger asChild>
        <Button
          variant="ghost"
          size="icon"
          className="relative"
          type="button"
          aria-label={t("toggleTheme")}
        >
          <Sun className="h-5 w-5 rotate-0 scale-100 transition-all dark:-rotate-90 dark:scale-0" />
          <Moon className="absolute h-5 w-5 rotate-90 scale-0 transition-all dark:rotate-0 dark:scale-100" />
          <span className="sr-only">{t("toggleTheme")}</span>
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-40">
        <DropdownMenuLabel>{t("theme")}</DropdownMenuLabel>
        <DropdownMenuRadioGroup
          value={theme}
          onValueChange={(value) => setTheme(value as "light" | "dark" | "system")}
        >
          <DropdownMenuRadioItem value="system">{t("themeSystem")}</DropdownMenuRadioItem>
          <DropdownMenuRadioItem value="light">{t("themeLight")}</DropdownMenuRadioItem>
          <DropdownMenuRadioItem value="dark">{t("themeDark")}</DropdownMenuRadioItem>
        </DropdownMenuRadioGroup>
        <DropdownMenuSeparator />
        <DropdownMenuLabel>{t("pride")}</DropdownMenuLabel>
        <DropdownMenuRadioGroup
          value={pride}
          onValueChange={(value) => setPride(value as PridePreference)}
        >
          <DropdownMenuRadioItem value="auto">{t("prideAuto")}</DropdownMenuRadioItem>
          <DropdownMenuRadioItem value="on">{t("prideOn")}</DropdownMenuRadioItem>
          <DropdownMenuRadioItem value="off">{t("prideOff")}</DropdownMenuRadioItem>
        </DropdownMenuRadioGroup>
      </DropdownMenuContent>
    </DropdownMenu>
  );
};
