import { useMemo } from "react";
import { useTranslation } from "react-i18next";

import { setTaskTagsApiV1TasksTaskIdTagsPut } from "@/api/generated/tasks/tasks";
import { invalidateAllTasks } from "@/api/query-keys";
import { BulkEditTagsDialog } from "@/components/shared/BulkEditTagsDialog";
import type { TaskListRead } from "@/api/generated/initiativeAPI.schemas";
import type { DialogWithSuccessProps } from "@/types/dialog";

interface BulkEditTaskTagsDialogProps extends DialogWithSuccessProps {
  tasks: TaskListRead[];
}

export function BulkEditTaskTagsDialog({ tasks, ...dialogProps }: BulkEditTaskTagsDialogProps) {
  const { t } = useTranslation(["tasks", "common"]);

  const labels = useMemo(
    () => ({
      title: t("bulkEditTags.title"),
      descriptionAdd: t("bulkEditTags.descriptionAdd", { count: tasks.length }),
      descriptionRemove: t("bulkEditTags.descriptionRemove", { count: tasks.length }),
      tabAdd: t("bulkEditTags.tabAdd"),
      tabRemove: t("bulkEditTags.tabRemove"),
      addPlaceholder: t("bulkEditTags.addPlaceholder"),
      removePlaceholder: t("bulkEditTags.removePlaceholder"),
      noTags: t("bulkEditTags.noTags"),
      tagsAdded: t("bulkEditTags.tagsAdded", { count: tasks.length }),
      tagsRemoved: t("bulkEditTags.tagsRemoved", { count: tasks.length }),
      applying: t("bulkEditTags.applying"),
      apply: t("bulkEditTags.apply"),
      cancel: t("common:cancel"),
      updateError: t("bulkEditTags.updateError"),
    }),
    [t, tasks.length]
  );

  return (
    <BulkEditTagsDialog
      {...dialogProps}
      items={tasks}
      setTags={(taskId, tagIds) => setTaskTagsApiV1TasksTaskIdTagsPut(taskId, { tag_ids: tagIds })}
      onInvalidate={() => void invalidateAllTasks()}
      labels={labels}
    />
  );
}
