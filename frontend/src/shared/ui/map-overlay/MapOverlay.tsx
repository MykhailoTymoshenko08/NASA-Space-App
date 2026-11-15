import { createContext, useContext, useEffect, useId, useMemo, useState, type ReactNode } from "react";
import { Icon } from "../icon";
import s from "./map-overlay.module.css";

/** Full-screen state of the enclosing MapStage, for the toggle in MapZoomControls. */
const StageContext = createContext<{ expanded: boolean; toggle: () => void } | null>(null);

/**
 * Bordered map frame. Overlays are absolutely placed children. On a phone it can fill the screen
 * (toggle in MapZoomControls, Escape leaves): the page around it then stops scrolling, so every drag
 * moves the map. The map resizes itself with its container.
 */
export function MapStage({ children, height = 720, id }: { children: ReactNode; height?: number; id?: string }) {
  const [expanded, setExpanded] = useState(false);
  useEffect(() => {
    if (!expanded) return;
    const root = document.documentElement;
    const overflow = root.style.overflow;
    root.style.overflow = "hidden";
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setExpanded(false);
    };
    window.addEventListener("keydown", onKey);
    return () => {
      root.style.overflow = overflow;
      window.removeEventListener("keydown", onKey);
    };
  }, [expanded]);
  const stage = useMemo(() => ({ expanded, toggle: () => setExpanded((v) => !v) }), [expanded]);
  return (
    <StageContext.Provider value={stage}>
      <div className={`${s.stage} ${expanded ? s.stageFull : ""}`} style={{ height }} id={id}>
        {children}
      </div>
    </StageContext.Provider>
  );
}

/**
 * Zoom in and out (DS-Map controls, 46 px), plus the full-screen toggle on phones. With `onReset`, a third
 * button (expand icon) shows the whole area again, e.g. the whole country on the landing map.
 */
export function MapZoomControls({
  onZoomIn,
  onZoomOut,
  onReset,
  resetLabel = "Show the whole country",
  children,
}: {
  onZoomIn: () => void;
  onZoomOut: () => void;
  onReset?: () => void;
  resetLabel?: string;
  children?: ReactNode;
}) {
  const stage = useContext(StageContext);
  return (
    <div className={s.controls}>
      {stage && (
        // Phones only (CSS), and always while full screen so there is a way back.
        <div className={`${s.zoom} ${s.fullGroup}`}>
          <button
            type="button"
            className={s.ctl}
            onClick={stage.toggle}
            aria-label={stage.expanded ? "Exit full screen" : "Show the map full screen"}
          >
            <Icon name={stage.expanded ? "minimize" : "maximize"} />
          </button>
        </div>
      )}
      <div className={s.zoom}>
        <button type="button" className={s.ctl} onClick={onZoomIn} aria-label="Zoom in">
          <Icon name="plus" />
        </button>
        <button type="button" className={s.ctl} onClick={onZoomOut} aria-label="Zoom out">
          <Icon name="minus" />
        </button>
        {onReset && (
          <button type="button" className={s.ctl} onClick={onReset} aria-label={resetLabel} title={resetLabel}>
            <Icon name="expand" />
          </button>
        )}
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

/** Legend card. On a phone it folds into a "Legend" button, so it does not cover half the map. */
export function MapLegend({ title, items, note }: { title?: string; items: readonly LegendItem[]; note?: string }) {
  const [open, setOpen] = useState(false);
  const bodyId = useId();
  return (
    <div className={`${s.legend} ${open ? s.legendOpen : ""}`}>
      <button
        type="button"
        className={s.legendToggle}
        aria-expanded={open}
        aria-controls={bodyId}
        onClick={() => setOpen((v) => !v)}
      >
        <Icon name="layers" size={18} />
        {open ? "Hide legend" : "Legend"}
      </button>
      <div id={bodyId} className={s.legendBody}>
        {title && <div className={s.legendTitle}>{title}</div>}
        {items.map((k) => (
          <div key={k.label} className={s.legendRow}>
            <span className={s.swatch} style={{ background: k.fill, borderColor: k.line }} aria-hidden="true" />
            {k.label}
          </div>
        ))}
        {note && <div className={s.legendNote}>{note}</div>}
      </div>
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
