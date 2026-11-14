import { useState, type FormEvent } from "react";
import { changePassword, clearSession, passwordOk } from "@/entities/session";
import { ApiError, friendlyMessage } from "@/shared/api";
import { Button } from "@/shared/ui/button";
import { Message } from "@/shared/ui/feedback";
import { PasswordField, TextField } from "@/shared/ui/form";
import s from "./change-password.module.css";

const WRONG_CURRENT = "Your current password is not right.";

/**
 * POST /auth/change-password. Success revokes every session, this one included, so the
 * session is cleared and the caller asks the user to sign in again.
 * A 401 with `details.reason: invalid_credentials` is a wrong current password; any other
 * 401 means the session itself ended (expired or revoked elsewhere).
 */
export function ChangePasswordForm({ onChanged, onSessionEnded }: { onChanged: () => void; onSessionEnded: () => void }) {
  const [current, setCurrent] = useState("");
  const [pw, setPw] = useState("");
  const [pw2, setPw2] = useState("");
  const [shown, setShown] = useState(false);
  const [tried, setTried] = useState(false);
  const [pending, setPending] = useState(false);
  const [currentServerErr, setCurrentServerErr] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const currentErr = (tried && !current ? "Enter your current password." : null) ?? currentServerErr;
  const pwErr = tried && !passwordOk(pw) ? "Use at least 8 characters with one letter and one number." : null;
  const pw2Err = tried && pw !== pw2 ? "The two passwords do not match." : null;

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setTried(true);
    setError(null);
    setCurrentServerErr(null);
    if (!current || !passwordOk(pw) || pw !== pw2) return;
    setPending(true);
    try {
      await changePassword(current, pw);
      onChanged();
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        if (err.details?.reason === "invalid_credentials") {
          setCurrentServerErr(WRONG_CURRENT);
        } else {
          clearSession();
          onSessionEnded();
        }
      } else {
        setError(friendlyMessage(err));
      }
    } finally {
      setPending(false);
    }
  };

  return (
    <form className={s.form} onSubmit={submit} noValidate>
      <PasswordField
        label="Current password"
        autoComplete="current-password"
        value={current}
        onChange={(e) => {
          setCurrent(e.target.value);
          setCurrentServerErr(null);
        }}
        error={currentErr}
        shown={shown}
        onShownChange={setShown}
        maxLength={128}
      />
      <TextField
        label="New password"
        type={shown ? "text" : "password"}
        autoComplete="new-password"
        value={pw}
        onChange={(e) => setPw(e.target.value)}
        error={pwErr}
        hint="At least 8 characters with one letter and one number."
        maxLength={128}
      />
      <TextField
        label="Repeat the new password"
        type={shown ? "text" : "password"}
        autoComplete="new-password"
        value={pw2}
        onChange={(e) => setPw2(e.target.value)}
        error={pw2Err}
        maxLength={128}
      />
      {error && (
        <Message tone="error" role="alert">
          {error}
        </Message>
      )}
      <Button type="submit" variant="primary" size="lg" block disabled={pending}>
        {pending ? "Saving…" : "Change password"}
      </Button>
    </form>
  );
}
