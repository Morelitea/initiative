import { ArrowUp, ArrowDown, ArrowUpDown } from "lucide-react";

export const SortIcon = ({ isSorted }: { isSorted: boolean | "asc" | "desc" }) => {
  if (!isSorted) return <ArrowUpDown className="h-4 w-4" aria-hidden="true" />;
  if (isSorted === "asc") return <ArrowUp className="h-4 w-4" aria-hidden="true" />;
  if (isSorted === "desc") return <ArrowDown className="h-4 w-4" aria-hidden="true" />;
};
