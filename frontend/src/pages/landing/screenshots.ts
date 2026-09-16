/**
 * The app's own screenshots, one pair per view.
 *
 * The landing page is themed by the visitor's own setting, so a dark shot on a
 * light page (or the reverse) is the one thing that makes it look borrowed.
 * Each view therefore ships both, captured at 1920×1080 from the real app, and
 * the page picks by the resolved theme.
 */

import documentDark from "@/assets/screenshots/document-dark.png";
import documentLight from "@/assets/screenshots/document-light.png";
import myTasksDark from "@/assets/screenshots/my-tasks-dark.png";
import myTasksLight from "@/assets/screenshots/my-tasks-light.png";
import projectDark from "@/assets/screenshots/project-dark.png";
import projectLight from "@/assets/screenshots/project-light.png";

export type ScreenshotView = "myTasks" | "project" | "document";

const SCREENSHOTS: Record<ScreenshotView, { light: string; dark: string }> = {
  myTasks: { light: myTasksLight, dark: myTasksDark },
  project: { light: projectLight, dark: projectDark },
  document: { light: documentLight, dark: documentDark },
};

export const screenshot = (view: ScreenshotView, isDark: boolean): string =>
  SCREENSHOTS[view][isDark ? "dark" : "light"];
