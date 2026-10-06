import { useParams } from "@tanstack/react-router";
import type { ReactNode } from "react";

import type { Tool } from "@/api/generated/initiativeAPI.schemas";
import { ToolSettingsLayout } from "@/components/tools/settings/ToolSettingsLayout";
import { TOOL_HOOKS } from "@/hooks/toolHooks";
import { toolCamelSingular } from "@/lib/tools";

/**
 * The settings of a tool that adds nothing to the shared sections but, at
 * most, a field in its Details card. Its data comes from the tool's
 * `TOOL_HOOKS` entry, for the id in the route's `<tool>Id` param.
 */
export const ToolSettingsPage = ({
  tool,
  detailsInline,
}: {
  tool: Tool;
  detailsInline?: ReactNode;
}) => {
  const params = useParams({ strict: false }) as Record<string, string | undefined>;
  const rawId = params[`${toolCamelSingular(tool)}Id`];
  const parsedId = rawId ? Number(rawId) : Number.NaN;
  const isValidId = Number.isFinite(parsedId);

  const { useDetail, useUpdate, useSetGrants, useDelete } = TOOL_HOOKS[tool];
  const query = useDetail(isValidId ? parsedId : null);
  const update = useUpdate(parsedId);
  const setGrants = useSetGrants(parsedId);
  const remove = useDelete();

  return (
    <ToolSettingsLayout
      tool={tool}
      entity={query.data}
      isLoading={isValidId && query.isLoading}
      isError={!isValidId || query.isError}
      update={update}
      setGrants={setGrants}
      remove={remove}
      detailsInline={detailsInline}
    />
  );
};
