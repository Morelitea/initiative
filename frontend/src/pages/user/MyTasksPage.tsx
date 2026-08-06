import { GlobalTasksPage } from "@/pages/user/GlobalTasksPage";

export const MyTasksPage = () => (
  <GlobalTasksPage
    view="assigned"
    storageKeyPrefix="my-tasks"
    columnsStorageKey="initiative-my-tasks-columns"
    i18nPrefix="myTasks"
  />
);
