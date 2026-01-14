export function setDomHiddenUntilFound(dom: HTMLElement): void {
  // @ts-expect-error - "until-found" is valid but not in types
  dom.hidden = "until-found";
}

export function domOnBeforeMatch(dom: HTMLElement, callback: () => void): void {
  dom.onbeforematch = callback;
}
