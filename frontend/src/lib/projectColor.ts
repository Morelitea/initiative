/** Distinct colors auto-assigned to projects on calendar views, so the same
 *  project maps to the same color across the initiative and project calendars. */
const PROJECT_COLORS = [
  "#3b82f6", // blue
  "#10b981", // emerald
  "#f59e0b", // amber
  "#ef4444", // red
  "#8b5cf6", // violet
  "#ec4899", // pink
  "#14b8a6", // teal
  "#f97316", // orange
  "#06b6d4", // cyan
  "#84cc16", // lime
];

export const getProjectColor = (projectId: number): string =>
  PROJECT_COLORS[projectId % PROJECT_COLORS.length];
