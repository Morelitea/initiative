/**
 * The guild home's tool switcher: one circle per tool, its name underneath.
 *
 * Each circle is a real link carrying `?tool=<route segment>`, so a tool view
 * is shareable, survives a reload, and answers the back button.
 */

import { Link } from "@tanstack/react-router";
import { useTranslation } from "react-i18next";

import type { Tool } from "@/api/generated/initiativeAPI.schemas";
import { useGuildPath } from "@/lib/guildUrl";
import { TOOL_REGISTRY, toolNavLabelKey, toolRouteSegment } from "@/lib/tools";
import { cn } from "@/lib/utils";

interface GuildToolRailProps {
  tools: Tool[];
  selected: Tool;
}

export const GuildToolRail = ({ tools, selected }: GuildToolRailProps) => {
  // `nav` leads so the derived tool label keys resolve without a namespace
  // prefix — the same call shape the sidebar uses.
  const { t } = useTranslation(["nav", "guildHome"]);
  const gp = useGuildPath();

  return (
    <nav aria-label={t("guildHome:toolRail")} className="-mx-2 overflow-x-auto px-2 pb-1">
      <ul className="flex min-w-max items-start gap-2 sm:gap-4">
        {tools.map((tool) => {
          const Icon = TOOL_REGISTRY[tool].icon;
          const isSelected = tool === selected;
          return (
            <li key={tool}>
              <Link
                to={gp("/")}
                search={{ tool: toolRouteSegment(tool) }}
                aria-current={isSelected ? "page" : undefined}
                className={cn(
                  "flex w-20 flex-col items-center gap-2 rounded-lg py-2 text-center outline-none transition-colors sm:w-24",
                  "focus-visible:ring-2 focus-visible:ring-ring",
                  isSelected ? "text-foreground" : "text-muted-foreground hover:text-foreground"
                )}
              >
                <span
                  className={cn(
                    "flex h-14 w-14 items-center justify-center rounded-full border transition-colors",
                    isSelected
                      ? "border-primary bg-primary/10 text-primary"
                      : "border-transparent bg-muted hover:bg-accent"
                  )}
                >
                  <Icon className="h-6 w-6" />
                </span>
                <span
                  className={cn(
                    "w-full truncate font-medium text-xs",
                    isSelected && "text-primary"
                  )}
                >
                  {t(toolNavLabelKey(tool))}
                </span>
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
};
