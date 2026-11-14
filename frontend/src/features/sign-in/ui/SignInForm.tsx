import { useState, type FormEvent } from "react";
import { Link } from "react-router";
import { emailError, signIn } from "@/entities/session";
import { ApiError, friendlyMessage, type User } from "@/shared/api";
import { APP_NAME, ROUTES } from "@/shared/config";
import { Button } from "@/shared/ui/button";
import { Message } from "@/shared/ui/feedback";
import { Checkbox, PasswordField, TextField } from "@/shared/ui/form";
import { Icon } from "@/shared/ui/icon";
import s from "./sign-in.module.css";

/** POST /auth/login. Calls `onSignedIn` with the user on success. */
export function SignInForm({ onSignedIn }: { onSignedIn: (user: User) => void }) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [remember, setRemember] = useState(true);
  const [tried, setTried] = useState(false);
  const [pending, setPending] = useState(false);
  const [serverError, setServerError] = useState<string | null>(null);

  const emailErr = tried ? emailError(email) : null;
  const pwErr = tried && !password ? "Enter your password." : null;

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setTried(true);
    setServerError(null);
    if (emailError(email) || !password) return;
    setPending(true);
    try {
      onSignedIn(await signIn({ email, password, remember }));
    } catch (err) {
      setServerError(
        err instanceof ApiError && err.code === "UNAUTHORIZED"
          ? "That email and password do not match an account. Check them and try again."
          : friendlyMessage(err),
      );
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
        maxLength={254}
      />
      <PasswordField
        label="Password"
        autoComplete="current-password"
        value={password}
        onChange={(e) => setPassword(e.target.value)}
        error={pwErr}
        maxLength={128}
      />
      <div className={s.row}>
        <Checkbox checked={remember} onChange={(e) => setRemember(e.target.checked)}>
          Keep me signed in
        </Checkbox>
        <Link to={ROUTES.resetPassword} className={s.link}>
          Forgot password?
        </Link>
      </div>
      {serverError && (
        <Message tone="error" role="alert">
          {serverError}
        </Message>
      )}
      <Button type="submit" variant="primary" size="lg" block disabled={pending}>
        {pending ? "Signing in…" : "Sign in"}
        {!pending && <Icon name="arrow-right" />}
      </Button>
      <p className={s.foot}>
        New to {APP_NAME}?{" "}
        <Link to={ROUTES.signUp} className={s.strong}>
          Create an account
        </Link>
      </p>
    </form>
  );
}
