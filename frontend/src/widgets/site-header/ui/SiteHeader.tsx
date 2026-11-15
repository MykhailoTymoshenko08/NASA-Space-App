import { useEffect, useId, useState } from "react";
import { useLocation } from "react-router";
import { useSession } from "@/entities/session";
import { AccountMenu } from "@/features/sign-out";
import { ROUTES } from "@/shared/config";
import { ButtonLink } from "@/shared/ui/button";
import { Wordmark } from "@/shared/ui/wordmark";
import s from "./site-header.module.css";

const AUTH_PAGES: readonly string[] = [ROUTES.signIn, ROUTES.signUp, ROUTES.resetPassword];

/**
 * Top bar, as in the desktop design. Landing: "How it works" (its #how section); other pages: "Explore the map".
 * The current page gets the wash fill and weight 600. Signed in: Saved fields + account menu. Auth pages: map links only.
 * At 760 px and narrower the links move into a burger menu that opens under the header (48 px rows).
 */
export function SiteHeader() {
  const { pathname, hash } = useLocation();
  const session = useSession();
  const here = (path: string) => pathname === path;
  const [menuOpen, setMenuOpen] = useState(false);
  const menuId = useId();

  // Close the menu after navigating, and on Escape.
  useEffect(() => setMenuOpen(false), [pathname, hash]);
  useEffect(() => {
    if (!menuOpen) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setMenuOpen(false);
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [menuOpen]);

  const onLanding = here(ROUTES.home);
  // Sign-in, sign-up and reset-password pages show only the two map links (design: boards 5 to 7).
  const authPage = AUTH_PAGES.some(here);

  const links = (row: boolean) => (
    <>
      {onLanding ? (
        <ButtonLink to={{ pathname: ROUTES.home, hash: "how" }} variant="ghost" className={row ? s.row : undefined}>
          How it works
        </ButtonLink>
      ) : (
        <ButtonLink to={ROUTES.home} variant="ghost" className={row ? s.row : undefined}>
          Explore the map
        </ButtonLink>
      )}
      <ButtonLink
        to={ROUTES.pickField}
        variant="ghost"
        current={here(ROUTES.pickField)}
        className={row ? s.row : undefined}
      >
        Pick a field
      </ButtonLink>
      {authPage ? null : session.status === "authenticated" ? (
        <>
          <ButtonLink
            to={ROUTES.myFields}
            variant="ghost"
            current={here(ROUTES.myFields)}
            className={row ? s.row : undefined}
          >
            Saved fields
          </ButtonLink>
          <ButtonLink
            to={ROUTES.areaRanking}
            variant="ghost"
            current={here(ROUTES.areaRanking)}
            className={row ? s.row : undefined}
          >
            Rank fields
          </ButtonLink>
          <AccountMenu email={session.user.email} block={row} />
        </>
      ) : (
        <ButtonLink
          to={ROUTES.signIn}
          variant="secondary"
          className={row ? s.row : undefined}
        >
          Sign in
        </ButtonLink>
      )}
    </>
  );

  return (
    <header className={s.header}>
      <Wordmark />
      <nav aria-label="Main" className={s.nav}>
        {links(false)}
      </nav>
      <button
        type="button"
        className={s.burger}
        aria-label="Menu"
        aria-expanded={menuOpen}
        aria-controls={menuId}
        onClick={() => setMenuOpen((v) => !v)}
      >
        <span className={s.burgerIcon} aria-hidden="true">
          <span />
          <span />
          <span />
        </span>
      </button>
      {/* Stays mounted so it can animate closed; inert + aria-hidden keep it out of reach while shut. */}
      <nav
        id={menuId}
        aria-label="Menu"
        className={s.menu}
        data-open={menuOpen}
        aria-hidden={!menuOpen}
        inert={!menuOpen}
      >
        <div className={s.menuClip}>
          <div className={s.menuInner}>{links(true)}</div>
        </div>
      </nav>
    </header>
  );
}
