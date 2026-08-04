import type { ReactNode } from "react";

import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";

export interface SettingsTab {
  value: string;
  label: string;
  path: string;
}

export interface SettingsTabsNavProps {
  /** Tabs to render as triggers; also the pool `onNavigate` resolves against. */
  tabs: SettingsTab[];
  /** Value of the currently active tab. */
  activeTab: string;
  /** Called with the selected tab's `path` when the user switches tabs. */
  onNavigate: (path: string) => void;
  /**
   * Optional content rendered inside `<Tabs>` after the tab bar. Used by
   * layouts (e.g. user settings) that render their `<Outlet/>` within the tab
   * context; layouts that render the outlet outside `<Tabs>` omit this.
   */
  children?: ReactNode;
}

/**
 * Presentational tab bar shared by the settings/admin tabbed layouts: the
 * `<Tabs>` shell, an overflow-scroll `<TabsList>`, and a `<TabsTrigger>` per
 * tab. Each layout keeps its own guards, header, and active-tab derivation.
 */
export function SettingsTabsNav({ tabs, activeTab, onNavigate, children }: SettingsTabsNavProps) {
  return (
    <Tabs
      value={activeTab}
      onValueChange={(value) => {
        const tab = tabs.find((item) => item.value === value);
        if (tab) {
          onNavigate(tab.path);
        }
      }}
    >
      <div className="-mx-4 overflow-x-auto pb-2 md:mx-0 md:overflow-visible">
        <TabsList className="w-full min-w-max justify-start gap-2 px-1 md:min-w-0">
          {tabs.map((tab) => (
            <TabsTrigger key={tab.value} value={tab.value} className="shrink-0">
              {tab.label}
            </TabsTrigger>
          ))}
        </TabsList>
      </div>
      {children}
    </Tabs>
  );
}
