import type { ReactNode } from "react";
import { Icon } from "../icon";
import s from "./map-overlay.module.css";

/** Bordered map frame. Overlays are absolutely placed children. */
export function MapStage({ children, height = 720, id }: { children: ReactNode; height?: number; id?: string }) {
  return (
    <div className={s.stage} style={{ height }} id={id}>
      {children}
    </div>
  );
}

/** Zoom in, zoom out and "show all" (DS-Map controls, 46 px). */
export function MapZoomControls({
  onZoomIn,
  onZoomOut,
  onReset,
  resetLabel,
  children,
}: {
  onZoomIn: () => void;
  onZoomOut: () => void;
  onReset: () => void;
  resetLabel: string;
  children?: ReactNode;
}) {
  return (
    <div className={s.controls}>
      <div className={s.zoom}>
        <button type="button" className={s.ctl} onClick={onZoomIn} aria-label="Zoom in">
          <Icon name="plus" />
        </button>
        <button type="button" className={s.ctl} onClick={onZoomOut} aria-label="Zoom out">
          <Icon name="minus" />
        </button>
        <button type="button" className={s.ctl} onClick={onReset} aria-label={resetLabel}>
          <Icon name="expand" />
        </button>
      </div>
      {children}
    </div>
  );
}

/** Four-step scale indicator; text alternative in the label. */
export function MapScaleSteps({ steps, current, label }: { steps: number; current: number; label: string }) {
  return (
    <div className={s.scale} role="img" aria-label={label}>
      {Array.from({ length: steps }, (_, i) => (
        <div key={i} className={`${s.scaleStep} ${i <= current ? s.scaleOn : ""}`} />
      ))}
    </div>
  );
}

export type LegendItem = { label: string; fill: string; line: string };

export function MapLegend({ title, items, note }: { title?: string; items: readonly LegendItem[]; note?: string }) {
  return (
    <div className={s.legend}>
      {title && <div className={s.legendTitle}>{title}</div>}
      {items.map((k) => (
        <div key={k.label} className={s.legendRow}>
          <span className={s.swatch} style={{ background: k.fill, borderColor: k.line }} aria-hidden="true" />
          {k.label}
        </div>
      ))}
      {note && <div className={s.legendNote}>{note}</div>}
    </div>
  );
}

/** Dark hint chip, announced politely. */
export function MapHint({ children }: { children: ReactNode }) {
  return (
    <div className={s.hint} role="status">
      {children}
    </div>
  );
}

/** Bottom row: legend left, hint and cards right. */
export function MapBottomBar({ children }: { children: ReactNode }) {
  return <div className={s.bottom}>{children}</div>;
}

/** Top-left toolbar (breadcrumbs, jump-to). */
export function MapTopBar({ children }: { children: ReactNode }) {
  return <div className={s.top}>{children}</div>;
}

/** Floating 320 px card on the map. */
export function MapCard({ children, label }: { children: ReactNode; label?: string }) {
  return (
    <div className={s.card} role="region" aria-label={label}>
      {children}
    </div>
  );
}

/** Centered message over an empty map. */
export function MapEmpty({ children }: { children: ReactNode }) {
  return (
    <div className={s.empty}>
      <Icon name="pin" size={40} />
      <div className={s.emptyText}>{children}</div>
    </div>
  );
}
