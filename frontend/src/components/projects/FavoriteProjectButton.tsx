import type { MouseEvent } from 'react';
import { Star } from 'lucide-react';

import { cn } from '../../lib/utils';
import { useProjectFavoriteMutation } from '../../hooks/useProjectFavoriteMutation';

interface FavoriteProjectButtonProps {
  projectId: number;
  isFavorited?: boolean;
  className?: string;
  suppressNavigation?: boolean;
  iconSize?: 'sm' | 'md';
}

export const FavoriteProjectButton = ({
  projectId,
  isFavorited = false,
  className,
  suppressNavigation = false,
  iconSize = 'md',
}: FavoriteProjectButtonProps) => {
  const favoriteMutation = useProjectFavoriteMutation();
  const pending =
    favoriteMutation.isPending && favoriteMutation.variables?.projectId === projectId;

  const handleClick = (event: MouseEvent<HTMLButtonElement>) => {
    if (suppressNavigation) {
      event.preventDefault();
      event.stopPropagation();
    }
    favoriteMutation.mutate({ projectId, nextState: !isFavorited });
  };

  const sizeClasses = iconSize === 'sm' ? 'h-7 w-7' : 'h-9 w-9';

  return (
    <button
      type="button"
      className={cn(
        'inline-flex items-center justify-center rounded-full border bg-background text-muted-foreground transition hover:text-amber-500 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-60',
        sizeClasses,
        className
      )}
      aria-pressed={isFavorited}
      aria-label={isFavorited ? 'Remove from favorites' : 'Add to favorites'}
      disabled={pending}
      onClick={handleClick}
    >
      <Star
        className={cn('h-4 w-4', isFavorited ? 'text-amber-500' : undefined)}
        fill={isFavorited ? 'currentColor' : 'none'}
      />
    </button>
  );
};
