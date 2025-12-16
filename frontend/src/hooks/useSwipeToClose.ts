import { useRef, useState } from "react";

interface UseSwipeToCloseProps {
  onClose: () => void;
  threshold?: number;
  direction?: "left" | "right";
}

export function useSwipeToClose({
  onClose,
  threshold = 50,
  direction = "left",
}: UseSwipeToCloseProps) {
  const startXRef = useRef<number>(0);
  const startYRef = useRef<number>(0);
  const [translateX, setTranslateX] = useState<number>(0);

  const handleTouchStart = (e: React.TouchEvent) => {
    startXRef.current = e.touches[0].clientX;
    startYRef.current = e.touches[0].clientY;
    setTranslateX(0);
  };

  const handleTouchMove = (e: React.TouchEvent) => {
    const currentX = e.touches[0].clientX;
    const currentY = e.touches[0].clientY;

    const deltaX = startXRef.current - currentX;
    const deltaY = Math.abs(startYRef.current - currentY);

    // Only apply transform if horizontal swipe is dominant
    if (Math.abs(deltaX) > deltaY) {
      if (direction === "left" && deltaX > 0) {
        // Swiping left: move sidebar left (negative transform)
        e.preventDefault();
        setTranslateX(-deltaX);
      } else if (direction === "right" && deltaX < 0) {
        // Swiping right: move sidebar right (positive transform)
        e.preventDefault();
        setTranslateX(-deltaX);
      }
    }
  };

  const handleTouchEnd = (e: React.TouchEvent) => {
    const endX = e.changedTouches[0].clientX;
    const endY = e.changedTouches[0].clientY;

    const deltaX = startXRef.current - endX;
    const deltaY = Math.abs(startYRef.current - endY);

    // Reset transform
    setTranslateX(0);

    // Only trigger if horizontal swipe is dominant (not vertical scrolling)
    if (deltaY < 50 && Math.abs(deltaX) > deltaY) {
      if (direction === "left" && deltaX > threshold) {
        onClose();
      } else if (direction === "right" && deltaX < -threshold) {
        onClose();
      }
    }
  };

  return {
    handleTouchStart,
    handleTouchMove,
    handleTouchEnd,
    translateX,
  };
}
