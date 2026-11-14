import { useState } from "react";
import { useSession } from "@/entities/session";
import { ChangePasswordForm } from "@/features/change-password";
import { ROUTES } from "@/shared/config";
import { useDocumentTitle } from "@/shared/lib";
import { ButtonLink } from "@/shared/ui/button";
import { Message, Skeleton } from "@/shared/ui/feedback";
import { Icon } from "@/shared/ui/icon";
import { FormCard } from "@/shared/ui/layout";

type Outcome = "form" | "done" | "ended";

const SIGN_IN_BACK = `${ROUTES.signIn}?next=${encodeURIComponent(ROUTES.changePassword)}`;

const COPY = {
  form: { title: "Change password", lead: "Enter your current password, then choose a new one." },
  done: { title: "Password changed", lead: "For your security we signed you out everywhere. Sign in with your new password." },
  ended: { title: "Sign in again", lead: "Your session ended before the password was changed." },
  signedOut: { title: "Change password", lead: "Sign in first to change your password." },
} as const;

/** Signed-in password change. Success revokes all sessions, so the page ends with "Sign in". */
export function ChangePasswordPage() {
  const session = useSession();
  const [outcome, setOutcome] = useState<Outcome>("form");
  const view = outcome !== "form" ? outcome : session.status === "anonymous" ? "signedOut" : "form";
  useDocumentTitle(COPY[view].title);

  if (view === "form" && session.status === "unknown") {
    return (
      <FormCard title={COPY.form.title} lead={COPY.form.lead}>
        <div role="status">
          <Skeleton height={48} />
          <span className="visually-hidden">Checking your session</span>
        </div>
      </FormCard>
    );
  }

  return (
    <FormCard title={COPY[view].title} lead={COPY[view].lead}>
      {view === "form" && <ChangePasswordForm onChanged={() => setOutcome("done")} onSessionEnded={() => setOutcome("ended")} />}

      {view === "done" && (
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

      {(view === "ended" || view === "signedOut") && (
        <>
          {view === "ended" && (
            <Message tone="error" role="alert">
              Your password was not changed. Sign in and try again.
            </Message>
          )}
          <ButtonLink to={SIGN_IN_BACK} variant="primary" size="lg" block>
            Sign in
            <Icon name="arrow-right" />
          </ButtonLink>
        </>
      )}
    </FormCard>
  );
}
