import { useState, type FormEvent } from "react";
import { Link } from "react-router";
import { emailError, passwordOk, passwordRules, signUp } from "@/entities/session";
import { ApiError, friendlyMessage, type User } from "@/shared/api";
import { ROUTES } from "@/shared/config";
import { Button } from "@/shared/ui/button";
import { Message } from "@/shared/ui/feedback";
import { Checkbox, InlineError, PasswordField, TextField } from "@/shared/ui/form";
import { Icon } from "@/shared/ui/icon";
import s from "./sign-up.module.css";

/**
 * POST /auth/register. The contract takes email and password only, so there is no name field
 * (design README, open question 4). Password rules mirror RegisterRequest.
 */
export function SignUpForm({ onSignedUp, next }: { onSignedUp: (user: User) => void; next?: string | null }) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [agree, setAgree] = useState(false);
  const [tried, setTried] = useState(false);
  const [pending, setPending] = useState(false);
  const [serverError, setServerError] = useState<{ text: string; taken: boolean } | null>(null);

  const rules = passwordRules(password);
  const emailErr = tried ? emailError(email) : null;
  const pwErr = tried && !passwordOk(password) ? "Your password does not meet the rules below." : null;

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setTried(true);
    setServerError(null);
    if (emailError(email) || !passwordOk(password) || !agree) return;
    setPending(true);
    try {
      onSignedUp(await signUp({ email, password }));
    } catch (err) {
      setServerError({
        text: friendlyMessage(err),
        taken: err instanceof ApiError && err.code === "EMAIL_TAKEN",
      });
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
        autoComplete="new-password"
        value={password}
        onChange={(e) => setPassword(e.target.value)}
        error={pwErr}
        maxLength={128}
        hint={
          <ul className={s.rules}>
            {rules.map((r) => (
              <li key={r.id} className={s.rule}>
                <Icon name={r.ok ? "check" : "dot"} size={16} />
                <span>
                  {r.ok ? "Done: " : "Needed: "}
                  {r.text}
                </span>
              </li>
            ))}
          </ul>
        }
      />
      <div>
        <Checkbox checked={agree} onChange={(e) => setAgree(e.target.checked)}>
          I agree to the terms and the privacy policy.
        </Checkbox>
        {tried && !agree && <InlineError>Agree to the terms to continue.</InlineError>}
      </div>
      {serverError && (
        <Message tone="error" role="alert">
          <span>{serverError.text}</span>
          {serverError.taken && (
            <Link to={next ? `${ROUTES.signIn}?next=${encodeURIComponent(next)}` : ROUTES.signIn} className={s.strong}>
              Sign in
            </Link>
          )}
        </Message>
      )}
      <Button type="submit" variant="primary" size="lg" block disabled={pending}>
        {pending ? "Creating account…" : "Create account"}
        {!pending && <Icon name="arrow-right" />}
      </Button>
      <p className={s.foot}>
        Already have an account?{" "}
        <Link to={next ? `${ROUTES.signIn}?next=${encodeURIComponent(next)}` : ROUTES.signIn} className={s.strong}>
          Sign in
        </Link>
      </p>
    </form>
  );
}
