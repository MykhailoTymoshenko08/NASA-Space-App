import { useState } from "react";
import { Link, useSearchParams } from "react-router";
import { canSimulateEmailLink, NewPasswordForm, RequestResetForm } from "@/features/reset-password";
import { ROUTES } from "@/shared/config";
import { useDocumentTitle } from "@/shared/lib";
import { Button, ButtonLink } from "@/shared/ui/button";
import { Message } from "@/shared/ui/feedback";
import { Icon } from "@/shared/ui/icon";
import { FormCard } from "@/shared/ui/layout";
import s from "./reset-password.module.css";

type Step = "request" | "sent" | "new" | "done";

const COPY: Record<Step, { title: string; lead: string }> = {
  request: { title: "Reset your password", lead: "Enter your email and we will send you a link to choose a new one." },
  sent: {
    title: "Check your email",
    lead: "If an account exists for that address, a reset link is on its way. The link works for 1 hour.",
  },
  new: { title: "Choose a new password", lead: "Use at least 8 characters with one letter and one number." },
  done: { title: "Password updated", lead: "You can now sign in with your new password." },
};

/**
 * Request link, sent, new password, done. The emailed link opens this page with ?token=..
 * The API calls are a stub until the contract has reset routes (see features/reset-password).
 */
export function ResetPasswordPage() {
  const [params] = useSearchParams();
  const urlToken = params.get("token");
  const [step, setStep] = useState<Step>(urlToken ? "new" : "request");
  const [email, setEmail] = useState("");
  const [token, setToken] = useState(urlToken ?? "");
  useDocumentTitle(COPY[step].title);

  return (
    <FormCard title={COPY[step].title} lead={COPY[step].lead}>
      {step === "request" && (
        <>
          <RequestResetForm
            initialEmail={email}
            onSent={(e) => {
              setEmail(e);
              setStep("sent");
            }}
          />
          <Link to={ROUTES.signIn} className={s.back}>
            <Icon name="arrow-left" size={18} />
            Back to sign in
          </Link>
        </>
      )}

      {step === "sent" && (
        <>
          <Message tone="success" role="status">
            <span>
              Link sent to <strong>{email}</strong>
            </span>
          </Message>
          <p className={s.muted}>Nothing there after a few minutes? Look in your spam folder, or send it again.</p>
          <Button variant="secondary" size="md" block onClick={() => setStep("request")}>
            Use a different email
          </Button>
          {canSimulateEmailLink() && (
            <Button
              variant="secondary"
              size="md"
              block
              onClick={() => {
                setToken("demo-token");
                setStep("new");
              }}
            >
              Demo: open the link from the email
            </Button>
          )}
        </>
      )}

      {step === "new" && <NewPasswordForm token={token} onSaved={() => setStep("done")} />}

      {step === "done" && (
        <>
          <Message tone="success" role="status">
            Your password was changed.
          </Message>
          <ButtonLink to={ROUTES.signIn} variant="primary" size="lg" block>
            Sign in
            <Icon name="arrow-right" />
          </ButtonLink>
        </>
      )}
    </FormCard>
  );
}
