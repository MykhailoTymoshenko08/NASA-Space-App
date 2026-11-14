/** Where ScrollRestoration (react-router) keeps scroll positions in sessionStorage. */
const SCROLL_POSITIONS_KEY = "react-router-scroll-positions";

/**
 * Entering or reloading the site starts at the top of the page. Call before the router is created:
 * on mount, ScrollRestoration scrolls to the URL's hash and restores the position saved before a
 * reload, both before any page code runs. So drop the landing page's #map anchor and the saved
 * positions here. Back and forward inside the app still restore positions saved from now on.
 */
export function resetEntryScroll(): void {
  if (typeof window === "undefined") return;
  try {
    window.sessionStorage.removeItem(SCROLL_POSITIONS_KEY);
  } catch {
    // Storage blocked (private mode): nothing was saved either.
  }
  const { hash, pathname, search } = window.location;
  if (hash === "#map") window.history.replaceState(window.history.state, "", pathname + search);
}
