/**
 * One provider's mark, at whatever size the place it sits in wants.
 *
 * Decorative: every place this appears names the provider beside it, so the
 * mark repeats what the label already says and is hidden from anything
 * reading the page aloud.
 */

import { FALLBACK_PROVIDER_ICON, providerIconUrl } from "@/lib/authProviderIcons";
import { cn } from "@/lib/utils";

export interface ProviderMarkProps {
  icon: string | null | undefined;
  className?: string;
}

export const ProviderMark = ({ icon, className }: ProviderMarkProps) => {
  const url = providerIconUrl(icon);
  if (url) {
    return <img src={url} alt="" aria-hidden="true" className={cn("h-5 w-5", className)} />;
  }
  const Fallback = FALLBACK_PROVIDER_ICON;
  return (
    <Fallback
      aria-hidden="true"
      className={cn("h-5 w-5 shrink-0 text-muted-foreground", className)}
    />
  );
};
