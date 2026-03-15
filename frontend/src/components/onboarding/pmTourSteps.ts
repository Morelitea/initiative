import type { Step } from "react-joyride";
import type { TFunction } from "i18next";

/** Sentinel for the "click Initiative Settings" step. */
export const PM_INITIATIVE_SETTINGS_STEP_ID = "pm-initiative-settings";
/** Index of the first step to show when the user is already on initiative settings. */
export const PM_TOUR_SETTINGS_START_INDEX = 2;
/** Sentinel for the Members tab step. */
export const PM_MEMBERS_TAB_STEP_ID = "pm-members-tab";
/** Sentinel for the Roles tab step. */
export const PM_ROLES_TAB_STEP_ID = "pm-roles-tab";

/**
 * Build steps for the standalone PM tour (9 steps).
 */
export const getPmTourSteps = (t: TFunction<"onboarding">): Step[] => [
  {
    target: "body",
    content: t("pmTour.welcome.body"),
    title: t("pmTour.welcome.title"),
    placement: "center",
    disableBeacon: true,
    data: { mood: "excited" },
  },
  {
    target: '[data-tour="initiative-settings"]',
    content: t("pmTour.initiativeSettings.body"),
    title: t("pmTour.initiativeSettings.title"),
    placement: "right-start",
    disableBeacon: true,
    data: { id: PM_INITIATIVE_SETTINGS_STEP_ID },
  },
  {
    target: '[data-tour="initiative-settings-page"]',
    content: t("pmTour.initiativeSettingsOverview.body"),
    title: t("pmTour.initiativeSettingsOverview.title"),
    placement: "bottom",
    disableBeacon: true,
    data: { mood: "proud" },
  },
  {
    target: '[data-tour="initiative-advanced-tools"]',
    content: t("pmTour.advancedTools.body"),
    title: t("pmTour.advancedTools.title"),
    placement: "top",
    disableBeacon: true,
  },
  {
    target: '[data-tour="initiative-tab-members"]',
    content: t("pmTour.membersTab.body"),
    title: t("pmTour.membersTab.title"),
    placement: "bottom",
    disableBeacon: true,
    data: { id: PM_MEMBERS_TAB_STEP_ID, hideNext: true },
  },
  {
    target: '[data-tour="initiative-members-tab"]',
    content: t("pmTour.membersTabContent.body"),
    title: t("pmTour.membersTabContent.title"),
    placement: "top",
    disableBeacon: true,
  },
  {
    target: '[data-tour="initiative-tab-roles"]',
    content: t("pmTour.rolesTab.body"),
    title: t("pmTour.rolesTab.title"),
    placement: "bottom",
    disableBeacon: true,
    data: { id: PM_ROLES_TAB_STEP_ID, hideNext: true },
  },
  {
    target: '[data-tour="initiative-roles-tab"]',
    content: t("pmTour.rolesTabContent.body"),
    title: t("pmTour.rolesTabContent.title"),
    placement: "top",
    disableBeacon: true,
  },
  {
    target: "body",
    content: t("pmTour.farewell.body"),
    title: t("pmTour.farewell.title"),
    placement: "center",
    disableBeacon: true,
  },
];
