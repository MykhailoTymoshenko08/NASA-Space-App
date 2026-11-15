import { useEffect, useState } from "react";
import logo from "../wordmark/logo.png";
import s from "./page-loader.module.css";

/** Full-screen loading screen: first app load, before the first route is ready. */
export function PageLoader({ label = "Loading page" }: { label?: string }) {
  return (
    <div className={s.screen} role="status" aria-live="polite">
      <img src={logo} alt="" width={70} height={64} className={s.mark} />
      <div className={s.track} aria-hidden="true">
        <div className={s.slide} />
      </div>
      <span className={s.label}>{label}…</span>
    </div>
  );
}

/**
 * Thin bar pinned to the top of the viewport while a route change is loading.
 * Waits `delay` ms before showing, so fast navigations do not flash.
 */
export function RouteProgress({ active, delay = 150 }: { active: boolean; delay?: number }) {
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    if (!active) {
      setVisible(false);
      return;
    }
    const timer = window.setTimeout(() => setVisible(true), delay);
    return () => window.clearTimeout(timer);
  }, [active, delay]);

  if (!visible) return null;
  return (
    <div className={s.routeBar} role="progressbar" aria-label="Loading page" aria-busy="true">
      <div className={s.routeSlide} />
    </div>
  );
}
