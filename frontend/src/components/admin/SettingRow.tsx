/**
 * The shared furniture of an operator settings sheet: a labelled control with
 * its explanation, and the headed group such rows sit in.
 *
 * Both operator sheets — one for a community, one for an account — are the same
 * kind of surface: a list of unrelated controls, each saving on its own. They
 * read alike because they are built from these two pieces.
 */

import { Label } from "@/components/ui/label";
import { Separator } from "@/components/ui/separator";
import { cn } from "@/lib/utils";

/** One labelled control with its explanation, so every row reads the same. */
export const SettingRow = ({
  label,
  help,
  htmlFor,
  control,
  indent = 0,
}: {
  label: string;
  help: string;
  htmlFor?: string;
  control: React.ReactNode;
  /** How far under the row above this reads as sitting: 0 stands on its own,
   * 1 is part of the row above it, 2 is part of that. */
  indent?: 0 | 1 | 2;
}) => (
  <div
    className={cn(
      "flex items-start justify-between gap-6 py-3",
      indent === 1 && "ml-3 border-border border-l pl-4",
      indent === 2 && "ml-7 border-border border-l pl-4"
    )}
  >
    <div className="space-y-1">
      <Label htmlFor={htmlFor} className="font-medium">
        {label}
      </Label>
      <p className="text-muted-foreground text-sm">{help}</p>
    </div>
    <div className="shrink-0 pt-0.5">{control}</div>
  </div>
);

export const Section = ({ title, children }: { title: string; children: React.ReactNode }) => (
  <section className="space-y-1">
    <h3 className="font-semibold text-sm">{title}</h3>
    <Separator />
    <div className="divide-y">{children}</div>
  </section>
);
