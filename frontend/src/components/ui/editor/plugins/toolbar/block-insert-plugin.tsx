import { useTranslation } from "react-i18next";
import { PlusIcon } from "lucide-react";

import { useEditorModal } from "@/components/ui/editor/editor-hooks/use-modal";
import { Select, SelectContent, SelectGroup, SelectTrigger } from "@/components/ui/select";

export function BlockInsertPlugin({ children }: { children: React.ReactNode }) {
  const [modal] = useEditorModal();
  const { t } = useTranslation("documents");

  return (
    <>
      {modal}
      <Select value={""}>
        <SelectTrigger className="h-8! w-min gap-1">
          <PlusIcon className="size-4" />
          <span>{t("editor.insert")}</span>
        </SelectTrigger>
        <SelectContent>
          <SelectGroup>{children}</SelectGroup>
        </SelectContent>
      </Select>
    </>
  );
}
