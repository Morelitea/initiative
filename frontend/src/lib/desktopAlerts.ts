/**
 * The notification stream's `alert` frames, handed to the desktop app.
 *
 * A frame names lines and nothing about them (`created`), or says a pause or
 * quiet hours held something back (`summary`). Only the desktop app sets a
 * handler; everywhere else a frame is passed over.
 */
export interface AlertFrame {
  action?: string;
  ids?: { notifications?: number[] };
}

let handler: ((frame: AlertFrame) => void) | null = null;

export const setAlertHandler = (next: ((frame: AlertFrame) => void) | null) => {
  handler = next;
};

export const receiveAlert = (frame: AlertFrame) => handler?.(frame);

/**
 * The unread count as an image, for the overlay on a Windows taskbar button,
 * which takes a picture rather than a number. `undefined` where there is no
 * canvas to draw on.
 */
export const drawBadge = (count: number): string | undefined => {
  const canvas = document.createElement("canvas");
  canvas.width = 32;
  canvas.height = 32;
  const context = canvas.getContext("2d");
  if (!context || count <= 0) {
    return undefined;
  }
  context.fillStyle = "#dc2626";
  context.beginPath();
  context.arc(16, 16, 16, 0, Math.PI * 2);
  context.fill();
  const label = count > 99 ? "99+" : String(count);
  context.fillStyle = "#ffffff";
  context.font = `bold ${[18, 18, 15, 12][label.length]}px sans-serif`;
  context.textAlign = "center";
  context.textBaseline = "middle";
  context.fillText(label, 16, 17);
  return canvas.toDataURL("image/png");
};
