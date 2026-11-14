import s from "./progress.module.css";

/** Determinate bar with its percent as text. */
export function ProgressBar({ percent, label }: { percent: number; label: string }) {
  const pct = Math.max(0, Math.min(100, Math.round(percent)));
  return (
    <div className={s.row}>
      <div role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={pct} aria-label={label} className={s.track}>
        <div className={s.bar} style={{ width: `${pct}%` }} />
      </div>
      <span className={s.pct} aria-hidden="true">
        {pct}%
      </span>
    </div>
  );
}

/** Sliding bar for work of unknown length. Hidden from screen readers; pair it with text. */
export function IndeterminateBar() {
  return (
    <div className={s.thin} aria-hidden="true">
      <div className={s.slide} />
    </div>
  );
}

/** Horizontal score bar (0 to 100), e.g. "Fit by topic". */
export function MeterBar({ percent, color, height = 8 }: { percent: number; color?: string; height?: number }) {
  return (
    <div className={s.meter} style={{ height, borderRadius: height / 2 }} aria-hidden="true">
      <div
        style={{
          width: `${Math.max(0, Math.min(100, percent))}%`,
          height,
          borderRadius: height / 2,
          background: color ?? "var(--color-green-700)",
        }}
      />
    </div>
  );
}
