import { useEffect, useId, useRef, useState } from "react";
import { Link, useNavigate } from "react-router";
import { signOut } from "@/entities/session";
import { ROUTES } from "@/shared/config";
import { Icon } from "@/shared/ui/icon";
import s from "./account-menu.module.css";

/** Round account button (44 px) with a small menu: who is signed in, Change password, and Sign out (POST /auth/logout). */
export function AccountMenu({ email }: { email: string }) {
  const [open, setOpen] = useState(false);
  const [pending, setPending] = useState(false);
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
    try {
      await signOut();
    } finally {
      setPending(false);
      setOpen(false);
      navigate(ROUTES.home);
    }
  };

  return (
    <div className={s.wrap} ref={wrap}>
      <button
        type="button"
        className={s.trigger}
        aria-label="Account"
        aria-expanded={open}
        aria-controls={menuId}
        onClick={() => setOpen((v) => !v)}
      >
        <Icon name="user" />
      </button>
      {open && (
        <div id={menuId} className={s.menu}>
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
        </div>
      )}
    </div>
  );
}
