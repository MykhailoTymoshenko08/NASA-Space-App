/** DS icon set: 24 px grid, 2 px stroke, round caps, drawn in currentColor. Always decorative here. */
const PATHS = {
  plus: "M12 5v14M5 12h14",
  minus: "M5 12h14",
  expand: "M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5",
  "arrow-right": "M5 12h14M13 6l6 6-6 6",
  "arrow-left": "M19 12H5M11 6l-6 6 6 6",
  chevron: "M9 6l6 6-6 6",
  layers: "M12 3l9 5-9 5-9-5 9-5zM3 13l9 5 9-5",
  pin: "M12 21s7-6.2 7-11a7 7 0 10-14 0c0 4.8 7 11 7 11zM12 12.5a2.5 2.5 0 100-5 2.5 2.5 0 000 5z",
  crosshair: "M12 3v4M12 17v4M3 12h4M17 12h4M12 15a3 3 0 100-6 3 3 0 000 6z",
  check: "M5 13l4 4L19 7",
  warning: "M12 8v5M12 17h.01M10.3 3.9L2.4 18a2 2 0 001.7 3h15.8a2 2 0 001.7-3L13.7 3.9a2 2 0 00-3.4 0z",
  info: "M12 11v5M12 8h.01M12 21a9 9 0 100-18 9 9 0 000 18z",
  download: "M12 4v11M7 11l5 5 5-5M5 20h14",
  close: "M6 6l12 12M18 6L6 18",
  user: "M12 12a4 4 0 100-8 4 4 0 000 8zM4 21a8 8 0 0116 0",
  bookmark: "M6 4h12v17l-6-4-6 4z",
  eye: "M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12zM12 15a3 3 0 100-6 3 3 0 000 6z",
  trash: "M4 7h16M10 11v6M14 11v6M6 7l1 13h10l1-13M9 7V4h6v3",
  columns: "M4 5h6v14H4zM14 5h6v14h-6z",
  file: "M14 3H7a2 2 0 00-2 2v14a2 2 0 002 2h10a2 2 0 002-2V8zM14 3v5h5M9 14h6M9 17h4",
  dot: "M12 12h.01",
} as const;

export type IconName = keyof typeof PATHS;

/** `filled` fills the shape too (a saved bookmark). */
export function Icon({ name, size = 20, filled = false }: { name: IconName; size?: number; filled?: boolean }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      aria-hidden="true"
      focusable="false"
      fill={filled ? "currentColor" : "none"}
      stroke="currentColor"
      strokeWidth={2}
      strokeLinecap="round"
      strokeLinejoin="round"
      style={{ flex: "none" }}
    >
      <path d={PATHS[name]} />
    </svg>
  );
}
