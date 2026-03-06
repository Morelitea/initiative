import type { Step } from "react-joyride";
import type { TFunction } from "i18next";

export type TourVariant = "new_user" | "guild_admin" | "superadmin";

/** Sentinel so OnboardingTour can detect the guild-list step. */
export const GUILD_LIST_STEP_ID = "guild-list";
/** Sentinel for the "click Guild Settings" step — optional detour. */
export const GUILD_SETTINGS_STEP_ID = "guild-settings";
/** Sentinel for the "click Platform Settings" step — waits for navigation. */
export const PLATFORM_SETTINGS_STEP_ID = "platform-settings";
/** Sentinel for the sidebar step — offers "explore on your own" exit. */
export const SIDEBAR_STEP_ID = "sidebar";
/** Sentinel for the initiatives/tasks step — waits for project click. */
export const TASKS_STEP_ID = "tasks";
/** Sentinel for the PM handoff step — triggers PM tour on navigation. */
export const PM_HANDOFF_STEP_ID = "pm-handoff";

/**
 * Build tour steps based on user role.
 * All users see: welcome → home tasks → user menu overview → guild list → …
 * Superadmins additionally get a "go to Platform Settings" step that waits
 * for them to navigate to /settings/admin, then an overview of that page.
 */
export const getTourSteps = (
  t: TFunction<"onboarding">,
  variant: TourVariant,
  isGuildAdmin: boolean,
  isProjectManager: boolean
): Step[] => {
  const welcome: Step = {
    target: "body",
    content: t("welcome.body"),
    title: t("welcome.title"),
    placement: "center",
    disableBeacon: true,
  };

  const homeTasks: Step = {
    target: '[data-tour="home-tasks"]',
    content: t("homeTasks.body"),
    title: t("homeTasks.title"),
    placement: "right",
    disableBeacon: true,
  };

  // Points to the user menu and explains the dropdown contents.
  // Superadmins get a variant that directs them to click Platform Settings.
  const menuOverviewStep: Step = {
    target: '[data-tour="platform-settings"]',
    content: variant === "superadmin" ? t("menuOverview.bodySuperadmin") : t("menuOverview.body"),
    title: t("menuOverview.title"),
    placement: "right",
    disableBeacon: true,
    disableOverlay: true,
    ...(variant === "superadmin"
      ? { data: { id: PLATFORM_SETTINGS_STEP_ID, hideNext: true } }
      : {}),
  };

  const adminSettingsOverviewStep: Step = {
    target: '[data-tour="admin-settings"]',
    content: t("adminSettingsOverview.body"),
    title: t("adminSettingsOverview.title"),
    placement: "bottom",
    disableBeacon: true,
    data: { mood: "proud" },
  };

  const brandingTabStep: Step = {
    target: '[data-tour="admin-branding-tab"]',
    content: t("brandingTab.body"),
    title: t("brandingTab.title"),
    placement: "bottom",
    disableBeacon: true,
    data: { mood: "winking" },
  };

  // --- Rest of the common tour ---

  const guildSettingsStep: Step = {
    target: '[data-tour="guild-settings"]',
    content: t("guildSettings.body"),
    title: t("guildSettings.title"),
    placement: "right-start",
    disableBeacon: true,
    data: { id: GUILD_SETTINGS_STEP_ID },
  };

  const guildSettingsOverviewStep: Step = {
    target: '[data-tour="guild-settings-page"]',
    content: t("guildSettingsOverview.body"),
    title: t("guildSettingsOverview.title"),
    placement: "bottom",
    disableBeacon: true,
    data: { mood: "proud" },
  };

  const restCommon: Step[] = [
    {
      target: '[data-tour="guild-list"]',
      content: t("guildList.body"),
      title: t("guildList.title"),
      placement: "right",
      disableBeacon: true,
      data: { id: GUILD_LIST_STEP_ID, hideNext: true },
    },
    // Guild admins see guild settings as the first step in the guild.
    // If they click the settings icon, they get an overview step.
    // If they click Next, the overview is skipped.
    ...(isGuildAdmin ? [guildSettingsStep, guildSettingsOverviewStep] : []),
    {
      target: '[data-tour="sidebar"]',
      content: t("sidebar.body"),
      title: t("sidebar.title"),
      placement: "right-start",
      disableBeacon: true,
      data: { id: SIDEBAR_STEP_ID, mood: "thinking" },
    },
    {
      target: '[data-tour="sidebar-view-toggle"]',
      content: t("viewToggle.body"),
      title: t("viewToggle.title"),
      placement: "right-start",
      disableBeacon: true,
    },
    {
      target: '[data-tour="tasks"]',
      content: t("tasks.body"),
      title: t("tasks.title"),
      placement: "right-start",
      disableBeacon: true,
      data: { id: TASKS_STEP_ID, hideNext: true },
    },
    {
      target: '[data-tour="project-views"]',
      content: t("projectViews.body"),
      title: t("projectViews.title"),
      placement: "bottom",
      disableBeacon: true,
    },
    {
      target: '[data-tour="project-filters"]',
      content: t("projectFilters.body"),
      title: t("projectFilters.title"),
      placement: "bottom",
      disableBeacon: true,
    },
    // PM handoff — directs PMs to click the initiative settings icon,
    // which ends main tour and starts the standalone PM tour.
    ...(isProjectManager
      ? [
          {
            target: '[data-tour="initiative-settings"]',
            content: t("pmHandoff.body"),
            title: t("pmHandoff.title"),
            placement: "right-start" as const,
            disableBeacon: true,
            data: { id: PM_HANDOFF_STEP_ID, mood: "winking" as const },
          },
        ]
      : []),
  ];

  const farewellBody =
    variant === "superadmin"
      ? t("farewell.bodySuperadmin")
      : variant === "guild_admin"
        ? t("farewell.bodyAdmin")
        : t("farewell.body");

  const farewell: Step = {
    target: "body",
    content: farewellBody,
    title: t("farewell.title"),
    placement: "center",
    disableBeacon: true,
  };

  const intro: Step[] = [welcome, homeTasks, menuOverviewStep];

  if (variant === "superadmin") {
    return [...intro, adminSettingsOverviewStep, brandingTabStep, ...restCommon, farewell];
  }

  if (variant === "guild_admin") {
    return [...intro, ...restCommon, farewell];
  }

  return [...intro, ...restCommon, farewell];
};
