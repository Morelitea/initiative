import { useParams } from "@tanstack/react-router";

import { Tool } from "@/api/generated/initiativeAPI.schemas";
import { ToolSettingsLayout } from "@/components/tools/settings/ToolSettingsLayout";
import {
  useDashboard,
  useDeleteDashboard,
  useSetDashboardGrants,
  useUpdateDashboard,
} from "@/hooks/useDashboards";

export const DashboardSettingsPage = () => {
  const { dashboardId } = useParams({ strict: false }) as { dashboardId?: string };
  const parsedId = dashboardId ? Number(dashboardId) : Number.NaN;
  const isValidId = Number.isFinite(parsedId);

  const dashboardQuery = useDashboard(isValidId ? parsedId : null);
  const update = useUpdateDashboard(parsedId);
  const setGrants = useSetDashboardGrants(parsedId);
  const remove = useDeleteDashboard();

  return (
    <ToolSettingsLayout
      tool={Tool.dashboard}
      entity={dashboardQuery.data}
      isLoading={isValidId && dashboardQuery.isLoading}
      isError={!isValidId || dashboardQuery.isError}
      update={update}
      setGrants={setGrants}
      remove={remove}
    />
  );
};
