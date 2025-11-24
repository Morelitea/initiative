export const truncateText = (value: string, limit = 50): string => {
  if (!value) {
    return "";
  }
  const trimmed = value.trim();
  if (trimmed.length <= limit) {
    return trimmed;
  }
  return `${trimmed.slice(0, limit).trimEnd()}…`;
};
