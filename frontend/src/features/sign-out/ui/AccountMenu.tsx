import { useEffect, useId, useRef, useState } from "react";
import { Link, useNavigate } from "react-router";
import { signOut } from "@/entities/session";
import { friendlyMessage } from "@/shared/api";
import { ROUTES } from "@/shared/config";
import { Message } from "@/shared/ui/feedback";
import { Icon } from "@/shared/ui/icon";
import s from "./account-menu.module.css";

/**
 * Round account button (44 px) with a small menu: who is signed in, Change password, and Sign out (POST /auth/logout).
 * `block`: full-width 48 px row labelled "Account", for the mobile burger menu.
 */
export function AccountMenu({ email, block = false }: { email: string; block?: boolean }) {
  const [open, setOpen] = useState(false);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const navigate = useNavigate();
  const menuId = useId();
  const wrap = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent | KeyboardEvent) => {
      if (e instanceof KeyboardEvent ? e.key === "Escape" : !wrap.current?.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", close);
    document.addEventListener("keydown", close);
    return () => {
      document.removeEventListener("mousedown", close);
      document.removeEventListener("keydown", close);
    };
  }, [open]);

  const onSignOut = async () => {
    setPending(true);
    setError(null);
    try {
      await signOut();
      setOpen(false);
      navigate(ROUTES.home);
    } catch (err) {
      setError(friendlyMessage(err));
    } finally {
      setPending(false);
    }
  };

  return (
    <div className={block ? `${s.wrap} ${s.wrapBlock}` : s.wrap} ref={wrap}>
      <button
        type="button"
        className={block ? `${s.trigger} ${s.triggerBlock}` : s.trigger}
        aria-label={block ? undefined : "Account"}
        aria-expanded={open}
        aria-controls={menuId}
        onClick={() => setOpen((v) => !v)}
      >
        <Icon name="user" />
        {block && "Account"}
      </button>
      {open && (
        <div id={menuId} className={block ? `${s.menu} ${s.menuBlock}` : s.menu}>
          <div className={s.who}>
            <span className={s.muted}>Signed in as</span>
            <span className={s.email}>{email}</span>
          </div>
          <Link to={ROUTES.changePassword} className={s.item} onClick={() => setOpen(false)}>
            Change password
          </Link>
          <button type="button" className={s.item} onClick={onSignOut} disabled={pending}>
            {pending ? "Signing out…" : "Sign out"}
          </button>
          {error && <Message tone="error" role="alert">{error}</Message>}
        </div>
      )}
    </div>
  );
}
