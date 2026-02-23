import "i18next";

import type auth from "../../public/locales/en/auth.json";
import type command from "../../public/locales/en/command.json";
import type common from "../../public/locales/en/common.json";
import type dashboard from "../../public/locales/en/dashboard.json";
import type dates from "../../public/locales/en/dates.json";
import type documents from "../../public/locales/en/documents.json";
import type errors from "../../public/locales/en/errors.json";
import type guilds from "../../public/locales/en/guilds.json";
import type importNs from "../../public/locales/en/import.json";
import type initiatives from "../../public/locales/en/initiatives.json";
import type landing from "../../public/locales/en/landing.json";
import type nav from "../../public/locales/en/nav.json";
import type notifications from "../../public/locales/en/notifications.json";
import type projects from "../../public/locales/en/projects.json";
import type settings from "../../public/locales/en/settings.json";
import type stats from "../../public/locales/en/stats.json";
import type tags from "../../public/locales/en/tags.json";
import type tasks from "../../public/locales/en/tasks.json";

declare module "i18next" {
  interface CustomTypeOptions {
    defaultNS: "common";
    fallbackNS: "common";
    returnNull: false;
    returnObjects: false;
    resources: {
      auth: typeof auth;
      command: typeof command;
      common: typeof common;
      dashboard: typeof dashboard;
      dates: typeof dates;
      documents: typeof documents;
      errors: typeof errors;
      guilds: typeof guilds;
      import: typeof importNs;
      initiatives: typeof initiatives;
      landing: typeof landing;
      nav: typeof nav;
      notifications: typeof notifications;
      projects: typeof projects;
      settings: typeof settings;
      stats: typeof stats;
      tags: typeof tags;
      tasks: typeof tasks;
    };
  }
}
