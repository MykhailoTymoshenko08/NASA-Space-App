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
} as const;

export type IconName = keyof typeof PATHS;

export function Icon({ name, size = 20 }: { name: IconName; size?: number }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      aria-hidden="true"
      focusable="false"
      fill="none"
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
