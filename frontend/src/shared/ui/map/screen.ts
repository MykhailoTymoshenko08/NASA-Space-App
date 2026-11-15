/** Phones (same breakpoint as the map stage CSS, shared/ui/map-overlay). */
const NARROW_SCREEN = "(max-width: 760px)";

const matches = (query: string) => typeof window !== "undefined" && window.matchMedia?.(query).matches === true;

/**
 * True on a phone. At the whole-country view a state is a few dozen pixels wide there, too small to tap:
 * the maps open on the field states instead and fit a tapped state no further out than its counties.
 */
export const isNarrowScreen = () => matches(NARROW_SCREEN);

/** A wide screen used with a mouse or trackpad (not a phone or a tablet held by touch). */
export const isDesktopPointer = () => !isNarrowScreen() && matches("(hover: hover) and (pointer: fine)");

/** "Tap" on touch screens, "Click" with a mouse, for map hints. */
export const tapWord = () => (matches("(pointer: coarse)") ? "Tap" : "Click");
