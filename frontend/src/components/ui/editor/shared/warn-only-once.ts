export function warnOnlyOnce(message: string) {
  if (import.meta.env.PROD) {
    return;
  }
  let run = false;
  return () => {
    if (!run) {
      console.warn(message);
    }
    run = true;
  };
}
