import { type ReactNode, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { Sheet, SheetContent, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { getItem, setItem } from "@/lib/storage";

const STORAGE_KEY = "file-side-panel-open";

/**
 * The file's AI summary, in a sheet beside the file.
 *
 * Comments used to share this panel as a second tab and no longer do — a thread
 * is a conversation and belongs at full width under the file, the same
 * place every other tool puts it, not in a column narrow enough to wrap every
 * reply.
 */
interface FileSidePanelProps {
  isOpen: boolean;
  onOpenChange: (open: boolean) => void;
  summaryContent: ReactNode;
}

export const FileSidePanel = ({ isOpen, onOpenChange, summaryContent }: FileSidePanelProps) => {
  const { t } = useTranslation("files");

  return (
    <Sheet open={isOpen} onOpenChange={onOpenChange}>
      <SheetContent
        side="right"
        className="flex w-full flex-col overflow-hidden p-0 medium:max-w-md"
      >
        <SheetHeader
          className="border-b px-4"
          style={{
            paddingTop: "calc(var(--safe-area-inset-top) + 0.75rem)",
            paddingBottom: "0.75rem",
          }}
        >
          <SheetTitle className="text-base">{t("sidePanel.summaryTab")}</SheetTitle>
        </SheetHeader>

        <div className="flex-1 overflow-y-auto p-4">{summaryContent}</div>
      </SheetContent>
    </Sheet>
  );
};

// Hook for managing panel state with storage persistence
export const useFileSidePanel = () => {
  const [isOpen, setIsOpen] = useState(() => {
    return getItem(STORAGE_KEY) === "true";
  });

  useEffect(() => {
    setItem(STORAGE_KEY, String(isOpen));
  }, [isOpen]);

  return {
    isOpen,
    setIsOpen,
    toggle: () => setIsOpen((prev) => !prev),
  };
};
