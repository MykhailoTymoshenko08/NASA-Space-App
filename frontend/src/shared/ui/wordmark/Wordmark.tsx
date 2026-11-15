import { Link } from "react-router";
import { APP_NAME, ROUTES } from "@/shared/config";
import s from "./wordmark.module.css";

/** Placeholder brand: furrow mark on Green 700 + the working name. */
export function Wordmark() {
  return (
    <Link to={ROUTES.home} className={s.wordmark}>
      <svg width="32" height="32" viewBox="0 0 32 32" aria-hidden="true" focusable="false">
        <rect width="32" height="32" rx="5" className={s.plate} />
        <path d="M7 21c5-4 13-4 18 0M7 16c5-4 13-4 18 0M7 11c5-4 13-4 18 0" className={s.furrows} />
      </svg>
      {APP_NAME}
      <span className="visually-hidden">, home</span>
    </Link>
  );
}
