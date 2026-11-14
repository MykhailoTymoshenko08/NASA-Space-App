import type { ReactNode } from "react";
import { Icon, type IconName } from "../icon";
import s from "./choice.module.css";

export type SegmentOption<T extends string | number> = { value: T; label: string; icon?: IconName };

/** One-of-many as pressed buttons on a wash track; the active one is Green 700 (DS "Segmented control"). */
export function SegmentedControl<T extends string | number>({
  label,
  options,
  value,
  onChange,
  fill = false,
}: {
  label: string;
  options: readonly SegmentOption<T>[];
  value: T;
  onChange: (value: T) => void;
  /** Equal-width options across the full row. */
  fill?: boolean;
}) {
  return (
    <div
      role="group"
      aria-label={label}
      className={`${s.track} ${fill ? s.fill : ""}`}
      style={fill ? { gridTemplateColumns: `repeat(${options.length}, minmax(0, 1fr))` } : undefined}
    >
      {options.map((o) => (
        <button
          key={String(o.value)}
          type="button"
          aria-pressed={o.value === value}
          className={`${s.segment} ${o.value === value ? s.on : ""}`}
          onClick={() => onChange(o.value)}
        >
          {o.icon && <Icon name={o.icon} size={18} />}
          {o.label}
        </button>
      ))}
    </div>
  );
}

/** Toggle chip (multi-select). The pressed state shows a check, not only color. */
export function ChipToggle({ pressed, onToggle, children }: { pressed: boolean; onToggle: () => void; children: ReactNode }) {
  return (
    <button type="button" aria-pressed={pressed} className={`${s.chip} ${pressed ? s.chipOn : ""}`} onClick={onToggle}>
      {pressed && <Icon name="check" size={16} />}
      {children}
    </button>
  );
}

/** Static pill, e.g. "2025 Corn". */
export function Pill({ children }: { children: ReactNode }) {
  return <span className={s.pill}>{children}</span>;
}
