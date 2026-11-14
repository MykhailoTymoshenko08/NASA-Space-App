import { ApiError, friendlyMessage, type ResolvedLocation } from "@/shared/api";
import { metersToFeet } from "@/shared/lib";

export type LocationMessage = { tone: "success" | "info" | "error"; text: string };

const near = (r: ResolvedLocation) => `${r.point.lat.toFixed(4)}, ${r.point.lon.toFixed(4)}`;

/** What to say after POST /locations/resolve (design copy). */
export function resolvedMessage(r: ResolvedLocation): LocationMessage {
  if (r.selection.resolved_by === "buffered_point") {
    const m = r.selection.buffer_m;
    const circle = m != null ? `a circle of ${Math.round(m)} m (${Math.round(metersToFeet(m))} ft)` : "a small circle";
    return {
      tone: "info",
      text: `Found ${near(r)}. There are no field outlines here yet, so we use ${circle} around your point.`,
    };
  }
  return { tone: "success", text: `Found ${near(r)}. We matched it to the nearest estimated field area.` };
}

export function errorMessage(err: unknown): LocationMessage {
  if (err instanceof ApiError) {
    switch (err.code) {
      case "UNPARSEABLE_INPUT":
        return {
          tone: "error",
          text: "We could not read that. Paste coordinates like 41.5868, -93.6250, or a Google Maps or Apple Maps link.",
        };
      case "UNSUPPORTED_LINK":
        return {
          tone: "error",
          text: "We know this link but could not find coordinates in it. Try the full link, or paste the coordinates.",
        };
      case "OUTSIDE_COVERAGE":
        return { tone: "error", text: "That point is outside the contiguous United States. Check the numbers and try again." };
      default:
        break;
    }
  }
  return { tone: "error", text: friendlyMessage(err) };
}

/** Short map links are opened on our server, which takes a moment. */
export const isShortLink = (text: string) => /maps\.app\.goo\.gl|goo\.gl\/maps|apple\.co\//i.test(text);
