import { cn } from './utils';

export const INITIATIVE_COLOR_FALLBACK = '#94a3b8';
const HEX_COLOR_REGEX = /^#(?:[0-9a-fA-F]{3}){1,2}$/i;

export const resolveInitiativeColor = (color?: string | null): string => {
  if (color && HEX_COLOR_REGEX.test(color)) {
    return color;
  }
  return INITIATIVE_COLOR_FALLBACK;
};

export const InitiativeColorDot = ({
  color,
  className,
}: {
  color?: string | null;
  className?: string;
}) => (
  <span
    className={cn('inline-block h-2.5 w-2.5 rounded-full', className)}
    style={{ backgroundColor: resolveInitiativeColor(color) }}
    aria-hidden="true"
  />
);
