import { useState } from "react";
import { useNavigate, useSearchParams } from "react-router";
import { SignInForm } from "@/features/sign-in";
import type { User } from "@/shared/api";
import { ROUTES } from "@/shared/config";
import { useDocumentTitle } from "@/shared/lib";
import { ButtonLink } from "@/shared/ui/button";
import { Message } from "@/shared/ui/feedback";
import { Icon } from "@/shared/ui/icon";
import { FormCard } from "@/shared/ui/layout";

/** Only same-site paths are allowed as a return target. */
const safeNext = (next: string | null) => (next && next.startsWith("/") && !next.startsWith("//") ? next : null);

export function SignInPage() {
  useDocumentTitle("Sign in");
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const next = safeNext(params.get("next"));
  const [user, setUser] = useState<User | null>(null);

  const onSignedIn = (u: User) => {
    if (next) navigate(next, { replace: true });
    else setUser(u);
  };

  return (
    <FormCard title="Sign in" lead="Welcome back. Sign in to see your saved fields.">
      {user ? (
        <>
          <Message tone="success" role="status">
            Signed in as {user.email}.
          </Message>
          <ButtonLink to={ROUTES.pickField} variant="primary" size="lg" block>
            Continue to Pick a field
            <Icon name="arrow-right" />
          </ButtonLink>
          <ButtonLink to={ROUTES.myFields} variant="secondary" size="md" block>
            Go to My fields
          </ButtonLink>
        </>
      ) : (
        <SignInForm onSignedIn={onSignedIn} />
      )}
    </FormCard>
  );
}
