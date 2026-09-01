import { type ReactNode, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { Sheet, SheetContent, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { Tabs, TabsBar, TabsContent, TabsTrigger } from "@/components/ui/tabs";
import { getItem, setItem } from "@/lib/storage";

const STORAGE_KEY = "document-side-panel-open";
const TAB_STORAGE_KEY = "document-side-panel-tab";

type PanelTab = "summary" | "comments";

interface DocumentSidePanelProps {
  isOpen: boolean;
  onOpenChange: (open: boolean) => void;
  summaryContent: ReactNode;
  commentsContent: ReactNode;
  showSummaryTab?: boolean;
  /** False when the document's comments are turned off in its settings. */
  showCommentsTab?: boolean;
}

export const DocumentSidePanel = ({
  isOpen,
  onOpenChange,
  summaryContent,
  commentsContent,
  showSummaryTab = true,
  showCommentsTab = true,
}: DocumentSidePanelProps) => {
  const { t } = useTranslation("documents");
  const [activeTab, setActiveTab] = useState<PanelTab>(() => {
    const saved = getItem(TAB_STORAGE_KEY);
    if (saved === "summary" && showSummaryTab) return "summary";
    return showCommentsTab ? "comments" : "summary";
  });

  // Persist tab selection
  useEffect(() => {
    setItem(TAB_STORAGE_KEY, activeTab);
  }, [activeTab]);

  // A hidden tab can't stay selected — fall through to the one still there.
  useEffect(() => {
    if (!showSummaryTab && activeTab === "summary") {
      setActiveTab("comments");
    } else if (!showCommentsTab && activeTab === "comments") {
      setActiveTab("summary");
    }
  }, [showSummaryTab, showCommentsTab, activeTab]);

  return (
    <Sheet open={isOpen} onOpenChange={onOpenChange}>
      <SheetContent side="right" className="flex w-full flex-col overflow-hidden p-0 sm:max-w-md">
        <SheetHeader
          className="border-b px-4"
          style={{
            paddingTop: "calc(var(--safe-area-inset-top) + 0.75rem)",
            paddingBottom: "0.75rem",
          }}
        >
          <SheetTitle className="text-base">{t("sidePanel.title")}</SheetTitle>
        </SheetHeader>

        <Tabs
          value={activeTab}
          onValueChange={(value) => setActiveTab(value as PanelTab)}
          className="flex flex-1 flex-col overflow-hidden"
        >
          {showSummaryTab && showCommentsTab && (
            <div className="px-3 pt-3">
              <TabsBar>
                <TabsTrigger value="comments">{t("sidePanel.commentsTab")}</TabsTrigger>
                <TabsTrigger value="summary">{t("sidePanel.summaryTab")}</TabsTrigger>
              </TabsBar>
            </div>
          )}

          <div className="flex-1 overflow-y-auto">
            {showCommentsTab && (
              <TabsContent
                value="comments"
                forceMount
                className="m-0 h-full p-4 data-[state=inactive]:hidden"
              >
                {commentsContent}
              </TabsContent>
            )}
            {showSummaryTab && (
              <TabsContent
                value="summary"
                forceMount
                className="m-0 h-full p-4 data-[state=inactive]:hidden"
              >
                {summaryContent}
              </TabsContent>
            )}
          </div>
        </Tabs>
      </SheetContent>
    </Sheet>
  );
};

// Hook for managing panel state with storage persistence
export const useDocumentSidePanel = () => {
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
