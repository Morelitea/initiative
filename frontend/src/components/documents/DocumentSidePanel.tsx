import { type ReactNode, useEffect, useState } from "react";

import { getItem, setItem } from "@/lib/storage";
import { Sheet, SheetContent, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";

const STORAGE_KEY = "document-side-panel-open";
const TAB_STORAGE_KEY = "document-side-panel-tab";

type PanelTab = "summary" | "comments";

interface DocumentSidePanelProps {
  isOpen: boolean;
  onOpenChange: (open: boolean) => void;
  summaryContent: ReactNode;
  commentsContent: ReactNode;
  showSummaryTab?: boolean;
}

export const DocumentSidePanel = ({
  isOpen,
  onOpenChange,
  summaryContent,
  commentsContent,
  showSummaryTab = true,
}: DocumentSidePanelProps) => {
  const [activeTab, setActiveTab] = useState<PanelTab>(() => {
    const saved = getItem(TAB_STORAGE_KEY);
    if (saved === "summary" && showSummaryTab) return "summary";
    return "comments";
  });

  // Persist tab selection
  useEffect(() => {
    setItem(TAB_STORAGE_KEY, activeTab);
  }, [activeTab]);

  // If summary tab is hidden but was selected, switch to comments
  useEffect(() => {
    if (!showSummaryTab && activeTab === "summary") {
      setActiveTab("comments");
    }
  }, [showSummaryTab, activeTab]);

  return (
    <Sheet open={isOpen} onOpenChange={onOpenChange}>
      <SheetContent side="right" className="flex w-full flex-col overflow-hidden p-0 sm:max-w-md">
        <SheetHeader className="border-b px-4 py-3">
          <SheetTitle className="text-base">Document Panel</SheetTitle>
        </SheetHeader>

        <Tabs
          value={activeTab}
          onValueChange={(value) => setActiveTab(value as PanelTab)}
          className="flex flex-1 flex-col overflow-hidden"
        >
          {showSummaryTab && (
            <TabsList className="mx-4 mt-3">
              <TabsTrigger value="comments" className="flex-1">
                Comments
              </TabsTrigger>
              <TabsTrigger value="summary" className="flex-1">
                Summary
              </TabsTrigger>
            </TabsList>
          )}

          <div className="flex-1 overflow-y-auto">
            <TabsContent
              value="comments"
              forceMount
              className="m-0 h-full p-4 data-[state=inactive]:hidden"
            >
              {commentsContent}
            </TabsContent>
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
