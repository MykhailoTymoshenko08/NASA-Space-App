import { useLocation } from "react-router";
import { useSession } from "@/entities/session";
import { AccountMenu } from "@/features/sign-out";
import { ROUTES } from "@/shared/config";
import { ButtonLink } from "@/shared/ui/button";
import { Wordmark } from "@/shared/ui/wordmark";
import s from "./site-header.module.css";

/** Top bar. The current page gets the wash fill and weight 600. Signed in: My fields + account menu. */
export function SiteHeader() {
  const { pathname } = useLocation();
  const session = useSession();
  const here = (path: string) => pathname === path;

  return (
    <header className={s.header}>
      <Wordmark />
      <nav aria-label="Main" className={s.nav}>
        <ButtonLink to={ROUTES.home} variant="ghost" current={here(ROUTES.home)}>
          Explore the map
        </ButtonLink>
        <ButtonLink to={ROUTES.pickField} variant="ghost" current={here(ROUTES.pickField)}>
          Pick a field
        </ButtonLink>
        {session.status === "authenticated" ? (
          <>
            <ButtonLink to={ROUTES.myFields} variant="ghost" current={here(ROUTES.myFields)}>
              My fields
            </ButtonLink>
            <AccountMenu email={session.user.email} />
          </>
        ) : (
          <ButtonLink to={ROUTES.signIn} variant="secondary" current={here(ROUTES.signIn)}>
            Sign in
          </ButtonLink>
        )}
      </nav>
    </header>
  );
}
