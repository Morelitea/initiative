import type { QueueRead } from "@/api/generated/initiativeAPI.schemas";
import {
  type CreateToolConfig,
  CreateToolDialog,
} from "@/components/initiativeTools/shared/CreateToolDialog";
import { useCreateQueue } from "@/hooks/useQueues";
import type { DialogProps } from "@/types/dialog";

type CreateQueueDialogProps = DialogProps & {
  /** If provided, the initiative is locked and cannot be changed */
  initiativeId?: number;
  /** If provided, pre-selects this initiative (but user can change it) */
  defaultInitiativeId?: number;
  /** Called after successful creation */
  onSuccess?: (queue: QueueRead) => void;
};

const QUEUE_CONFIG: CreateToolConfig<QueueRead> = {
  namespace: "queues",
  titleKey: "createQueue",
  descriptionKey: "noQueuesDescription",
  idPrefix: "create-queue",
  useCreate: useCreateQueue,
};

export const CreateQueueDialog = (props: CreateQueueDialogProps) => (
  <CreateToolDialog<QueueRead> config={QUEUE_CONFIG} {...props} />
);
