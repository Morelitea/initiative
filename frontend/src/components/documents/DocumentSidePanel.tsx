import { type ReactNode, useEffect, useState } from "react";

import { Sheet, SheetContent, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { cn } from "@/lib/utils";

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
    if (typeof window === "undefined") return "comments";
    const saved = localStorage.getItem(TAB_STORAGE_KEY);
    if (saved === "summary" && showSummaryTab) return "summary";
    return "comments";
  });

  // Persist tab selection
  useEffect(() => {
    localStorage.setItem(TAB_STORAGE_KEY, activeTab);
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
          <TabsList className={cn("mx-4 mt-3", !showSummaryTab && "hidden")}>
            <TabsTrigger value="comments" className="flex-1">
              Comments
            </TabsTrigger>
            {showSummaryTab && (
              <TabsTrigger value="summary" className="flex-1">
                Summary
              </TabsTrigger>
            )}
          </TabsList>

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

// Hook for managing panel state with localStorage persistence
export const useDocumentSidePanel = () => {
  const [isOpen, setIsOpen] = useState(() => {
    if (typeof window === "undefined") return false;
    const saved = localStorage.getItem(STORAGE_KEY);
    return saved === "true";
  });

  useEffect(() => {
    localStorage.setItem(STORAGE_KEY, String(isOpen));
  }, [isOpen]);

  return {
    isOpen,
    setIsOpen,
    toggle: () => setIsOpen((prev) => !prev),
  };
};
