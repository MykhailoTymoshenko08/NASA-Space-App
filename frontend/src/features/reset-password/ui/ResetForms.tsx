import { useState, type FormEvent } from "react";
import { emailError, passwordOk } from "@/entities/session";
import { Button } from "@/shared/ui/button";
import { Message } from "@/shared/ui/feedback";
import { PasswordField, TextField } from "@/shared/ui/form";
import { Icon } from "@/shared/ui/icon";
import { passwordResetApi } from "../api/password-reset-api";
import s from "./reset.module.css";

const messageOf = (err: unknown) => (err instanceof Error ? err.message : "Something went wrong. Try again.");

/** Step 1: email in, "Send reset link". */
export function RequestResetForm({ initialEmail = "", onSent }: { initialEmail?: string; onSent: (email: string) => void }) {
  const [email, setEmail] = useState(initialEmail);
  const [tried, setTried] = useState(false);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const emailErr = tried ? emailError(email) : null;

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setTried(true);
    setError(null);
    if (emailError(email)) return;
    setPending(true);
    try {
      await passwordResetApi.requestLink(email.trim());
      onSent(email.trim());
    } catch (err) {
      setError(messageOf(err));
    } finally {
      setPending(false);
    }
  };

  return (
    <form className={s.form} onSubmit={submit} noValidate>
      <TextField
        label="Email"
        type="email"
        autoComplete="email"
        placeholder="name@example.com"
        value={email}
        onChange={(e) => setEmail(e.target.value)}
        error={emailErr}
      />
      {error && (
        <Message tone="error" role="alert">
          {error}
        </Message>
      )}
      <Button type="submit" variant="primary" size="lg" block disabled={pending}>
        {pending ? "Sending…" : "Send reset link"}
        {!pending && <Icon name="arrow-right" />}
      </Button>
    </form>
  );
}

/** Step 3: new password twice, "Save new password". */
export function NewPasswordForm({ token, onSaved }: { token: string; onSaved: () => void }) {
  const [pw, setPw] = useState("");
  const [pw2, setPw2] = useState("");
  const [shown, setShown] = useState(false);
  const [tried, setTried] = useState(false);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const pwErr = tried && !passwordOk(pw) ? "Use at least 8 characters with one letter and one number." : null;
  const pw2Err = tried && pw !== pw2 ? "The two passwords do not match." : null;

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setTried(true);
    setError(null);
    if (!passwordOk(pw) || pw !== pw2) return;
    setPending(true);
    try {
      await passwordResetApi.setNewPassword(token, pw);
      onSaved();
    } catch (err) {
      setError(messageOf(err));
    } finally {
      setPending(false);
    }
  };

  return (
    <form className={s.form} onSubmit={submit} noValidate>
      <PasswordField
        label="New password"
        autoComplete="new-password"
        value={pw}
        onChange={(e) => setPw(e.target.value)}
        error={pwErr}
        shown={shown}
        onShownChange={setShown}
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
        {pending ? "Saving…" : "Save new password"}
      </Button>
    </form>
  );
}
