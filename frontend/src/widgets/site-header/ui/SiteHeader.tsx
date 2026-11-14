import { useLocation } from "react-router";
import { ROUTES } from "@/shared/config";
import { ButtonLink, buttonClass } from "@/shared/ui/button";
import { Wordmark } from "@/shared/ui/wordmark";
import s from "./site-header.module.css";

/** Top bar. The current page gets the Paper wash fill and weight 600. */
export function SiteHeader() {
  const { pathname } = useLocation();
  const onHome = pathname === ROUTES.home;

  return (
    <header className={s.header}>
      <Wordmark />
      <nav aria-label="Main" className={s.nav}>
        {onHome ? (
          <a href="#how" className={buttonClass({ variant: "ghost" })}>
            How it works
          </a>
        ) : (
          <ButtonLink to={ROUTES.home} variant="ghost">
            Explore the map
          </ButtonLink>
        )}
        <ButtonLink to={ROUTES.pickField} variant="ghost" current={pathname === ROUTES.pickField}>
          Pick a field
        </ButtonLink>
        <ButtonLink to={ROUTES.signIn} variant="secondary" current={pathname === ROUTES.signIn}>
          Sign in
        </ButtonLink>
      </nav>
    </header>
  );
}
