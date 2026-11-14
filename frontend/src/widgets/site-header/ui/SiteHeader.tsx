import { useEffect, useId, useState } from "react";
import { useLocation } from "react-router";
import { useSession } from "@/entities/session";
import { AccountMenu } from "@/features/sign-out";
import { ROUTES } from "@/shared/config";
import { ButtonLink } from "@/shared/ui/button";
import { Icon } from "@/shared/ui/icon";
import { Wordmark } from "@/shared/ui/wordmark";
import s from "./site-header.module.css";

/**
 * Top bar. The current page gets the wash fill and weight 600. Signed in: My fields + account menu.
 * At 760 px and narrower the links move into a burger menu that opens under the header (48 px rows).
 */
export function SiteHeader() {
  const { pathname } = useLocation();
  const session = useSession();
  const here = (path: string) => pathname === path;
  const [menuOpen, setMenuOpen] = useState(false);
  const menuId = useId();

  // Close the menu after navigating, and on Escape.
  useEffect(() => setMenuOpen(false), [pathname]);
  useEffect(() => {
    if (!menuOpen) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setMenuOpen(false);
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [menuOpen]);

  const links = (row: boolean) => (
    <>
      <ButtonLink to={ROUTES.home} variant="ghost" current={here(ROUTES.home)} className={row ? s.row : undefined}>
        Explore the map
      </ButtonLink>
      <ButtonLink
        to={ROUTES.pickField}
        variant="ghost"
        current={here(ROUTES.pickField)}
        className={row ? s.row : undefined}
      >
        Pick a field
      </ButtonLink>
      {session.status === "authenticated" ? (
        <>
          <ButtonLink
            to={ROUTES.myFields}
            variant="ghost"
            current={here(ROUTES.myFields)}
            className={row ? s.row : undefined}
          >
            My fields
          </ButtonLink>
          <AccountMenu email={session.user.email} block={row} />
        </>
      ) : (
        <ButtonLink
          to={ROUTES.signIn}
          variant="secondary"
          current={here(ROUTES.signIn)}
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
        <Icon name={menuOpen ? "close" : "menu"} size={22} />
      </button>
      {menuOpen && (
        <nav id={menuId} aria-label="Menu" className={s.menu}>
          {links(true)}
        </nav>
      )}
    </header>
  );
}
