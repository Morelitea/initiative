import type { DashboardRead } from "@/api/generated/initiativeAPI.schemas";
import { Tool } from "@/api/generated/initiativeAPI.schemas";
import {
  type CreateToolConfig,
  CreateToolDialog,
} from "@/components/initiativeTools/shared/CreateToolDialog";
import { useCreateDashboard } from "@/hooks/useDashboards";
import type { DialogProps } from "@/types/dialog";

type CreateDashboardDialogProps = DialogProps & {
  initiativeId?: number;
  defaultInitiativeId?: number;
  onSuccess?: (dashboard: DashboardRead) => void;
};

const DASHBOARD_CONFIG: CreateToolConfig<DashboardRead> = {
  tool: Tool.dashboard,
  namespace: "dashboards",
  titleKey: "createDashboard",
  descriptionKey: "noDashboardsDescription",
  idPrefix: "create-dashboard",
  useCreate: useCreateDashboard,
};

export const CreateDashboardDialog = (props: CreateDashboardDialogProps) => (
  <CreateToolDialog<DashboardRead> config={DASHBOARD_CONFIG} {...props} />
);
