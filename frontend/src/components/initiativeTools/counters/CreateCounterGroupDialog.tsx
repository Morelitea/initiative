import type { CounterGroupRead } from "@/api/generated/initiativeAPI.schemas";
import { Tool } from "@/api/generated/initiativeAPI.schemas";
import {
  type CreateToolConfig,
  CreateToolDialog,
} from "@/components/initiativeTools/shared/CreateToolDialog";
import { useCreateCounterGroup } from "@/hooks/useCounters";
import type { DialogProps } from "@/types/dialog";

type CreateCounterGroupDialogProps = DialogProps & {
  initiativeId?: number;
  defaultInitiativeId?: number;
  onSuccess?: (group: CounterGroupRead) => void;
};

const COUNTER_GROUP_CONFIG: CreateToolConfig<CounterGroupRead> = {
  tool: Tool.counter_group,
  namespace: "counterGroups",
  titleKey: "createGroup",
  descriptionKey: "noGroupsDescription",
  idPrefix: "create-counter-group",
  useCreate: useCreateCounterGroup,
};

export const CreateCounterGroupDialog = (props: CreateCounterGroupDialogProps) => (
  <CreateToolDialog<CounterGroupRead> config={COUNTER_GROUP_CONFIG} {...props} />
);
