import { GlobalTasksPage } from "@/pages/user/GlobalTasksPage";

export const MyCreatedTasksPage = () => (
  <GlobalTasksPage
    view="created"
    storageKeyPrefix="created-tasks"
    columnsStorageKey="initiative-created-tasks-columns"
    showAssignees
    i18nPrefix="createdTasks"
  />
);
