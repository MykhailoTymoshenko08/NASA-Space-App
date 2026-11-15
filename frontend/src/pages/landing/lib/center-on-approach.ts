import { useEffect, type RefObject } from "react";

/** How far the element's middle sits below (+) or above (-) the window's middle, in px. */
export const offsetFromCenter = (rect: { top: number; height: number }, viewportHeight: number) =>
  rect.top + rect.height / 2 - viewportHeight / 2;

/**
 * Center the element after a scroll that moved it toward the window's middle and stopped within
 * `reach` px of it. A scroll away from it, or past its middle, is left alone, so the page scrolls on
 * past the element freely.
 */
export function shouldCenter(startOffset: number, endOffset: number, reach: number): boolean {
  const end = Math.abs(endOffset);
  if (end < 2 || end > reach) return false;
  return Math.sign(startOffset) === Math.sign(endOffset) && end < Math.abs(startOffset);
}

const SETTLE_MS = 150;

/**
 * While `enabled()` holds (checked on each scroll), scrolling toward the element and stopping once it
 * fills about half the window scrolls the page so the element sits in the middle of the window.
 * A CSS scroll snap did the same but kept pulling the page back to the element when scrolling on.
 */
export function useCenterOnApproach(
  ref: RefObject<HTMLElement | null>,
  enabled: () => boolean,
  reducedMotion: () => boolean,
): void {
  useEffect(() => {
    const offset = () => {
      const el = ref.current;
      return el ? offsetFromCenter(el.getBoundingClientRect(), window.innerHeight) : null;
    };
    // Offset while the page was last at rest: where the next scroll starts from.
    let rest = offset();
    let timer: number | undefined;

    const onEnd = () => {
      const start = rest;
      const end = offset();
      rest = end;
      if (start === null || end === null || !enabled()) return;
      if (!shouldCenter(start, end, window.innerHeight / 2)) return;
      // Its own scroll ends with the element centered, which shouldCenter leaves alone.
      window.scrollTo({ top: window.scrollY + end, behavior: reducedMotion() ? "auto" : "smooth" });
    };
    const onResize = () => {
      rest = offset();
    };

    // scrollend where supported (not Safari yet); otherwise the scroll counts as ended after a pause.
    const hasScrollEnd = "onscrollend" in window;
    const onScroll = () => {
      window.clearTimeout(timer);
      timer = window.setTimeout(onEnd, SETTLE_MS);
    };

    if (hasScrollEnd) window.addEventListener("scrollend", onEnd);
    else window.addEventListener("scroll", onScroll, { passive: true });
    window.addEventListener("resize", onResize);
    return () => {
      window.removeEventListener("scrollend", onEnd);
      window.removeEventListener("scroll", onScroll);
      window.removeEventListener("resize", onResize);
      window.clearTimeout(timer);
    };
  }, [ref, enabled, reducedMotion]);
}
