import { Link, useNavigate } from "@tanstack/react-router";
import { Plus } from "lucide-react";
import type { MouseEvent } from "react";
import { useTranslation } from "react-i18next";

import type { Tool } from "@/api/generated/initiativeAPI.schemas";
import { Button } from "@/components/ui/button";
import { DropdownMenuItem } from "@/components/ui/dropdown-menu";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { useGuildPath } from "@/lib/guildUrl";
import { TOOL_REGISTRY, toolCreateLabelKey, toolCreateTarget } from "@/lib/tools";

/**
 * The single source of "how do I create this tool" — derived entirely from the
 * registry, so adding a tool gives it a create affordance automatically.
 *
 * In-app tools (`inAppCreate: true`) navigate to their list route's create
 * dialog. Hand-off tools (`inAppCreate: false`, e.g. the advanced tool) navigate
 * to their embedded page with a FRESH `create` token per click: re-clicking
 * while already on that page still re-fires the embed's "open create" signal
 * (the page turns the token into a postMessage; a static value would be a no-op
 * navigation). The Link's href stays intact for middle-/right-click.
 */
export function useToolCreate(tool: Tool, initiativeId: number) {
  const gp = useGuildPath();
  const navigate = useNavigate();
  const { t } = useTranslation("nav");

  const target = toolCreateTarget(tool, initiativeId);
  const to = gp(target.to);
  const label = t(toolCreateLabelKey(tool));

  const onClick = TOOL_REGISTRY[tool].inAppCreate
    ? undefined
    : (e: MouseEvent<HTMLAnchorElement>) => {
        e.preventDefault();
        navigate({ to, search: { create: String(Date.now()) } });
      };

  return { to, search: target.search, label, onClick };
}

type ToolCreateButtonProps = {
  tool: Tool;
  initiativeId: number;
  /**
   * `icon` — hover-reveal "+" for a sidebar tool row (expects a `group/tool`
   * ancestor). `menu-item` — a dropdown entry. `button` — a full "New X" button.
   */
  variant: "icon" | "menu-item" | "button";
};

/**
 * The one create affordance reused across every surface. All per-tool behavior
 * (destination, label, hand-off vs dialog) comes from `useToolCreate`; this only
 * chooses the presentation.
 */
export function ToolCreateButton({ tool, initiativeId, variant }: ToolCreateButtonProps) {
  const { to, search, label, onClick } = useToolCreate(tool, initiativeId);

  if (variant === "menu-item") {
    return (
      <DropdownMenuItem asChild>
        <Link to={to} search={search} onClick={onClick}>
          <Plus className="mr-2 h-4 w-4" />
          {label}
        </Link>
      </DropdownMenuItem>
    );
  }

  if (variant === "button") {
    return (
      <Button asChild size="sm">
        <Link to={to} search={search} onClick={onClick}>
          <Plus className="mr-2 h-4 w-4" />
          {label}
        </Link>
      </Button>
    );
  }

  return (
    <Tooltip delayDuration={300}>
      <TooltipTrigger asChild>
        <Button
          variant="ghost"
          size="icon"
          className="hidden h-6 w-6 shrink-0 opacity-0 transition-opacity group-hover/tool:opacity-100 lg:flex"
          asChild
        >
          <Link to={to} search={search} onClick={onClick} aria-label={label}>
            <Plus className="h-3 w-3" />
          </Link>
        </Button>
      </TooltipTrigger>
      <TooltipContent side="top">
        <p>{label}</p>
      </TooltipContent>
    </Tooltip>
  );
}
