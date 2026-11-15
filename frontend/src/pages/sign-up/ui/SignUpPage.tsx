import { useState } from "react";
import { useNavigate, useSearchParams } from "react-router";
import { SignUpForm } from "@/features/sign-up";
import type { User } from "@/shared/api";
import { ROUTES } from "@/shared/config";
import { safeNext, useDocumentTitle } from "@/shared/lib";
import { ButtonLink } from "@/shared/ui/button";
import { Message } from "@/shared/ui/feedback";
import { Icon } from "@/shared/ui/icon";
import { FormCard } from "@/shared/ui/layout";

export function SignUpPage() {
  useDocumentTitle("Create your account");
  const [user, setUser] = useState<User | null>(null);
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const next = safeNext(params.get("next"));
  const onSignedUp = (created: User) => {
    if (next) navigate(next, { replace: true });
    else setUser(created);
  };
  return (
    <FormCard title="Create your account" lead="Save fields and compare them. It takes a minute.">
      {user ? (
        <>
          <Message tone="success" role="status">
            Account created. You are signed in as {user.email}.
          </Message>
          <ButtonLink to={ROUTES.pickField} variant="primary" size="lg" block>
            Pick your first field
            <Icon name="arrow-right" />
          </ButtonLink>
        </>
      ) : (
        <SignUpForm onSignedUp={onSignedUp} next={next} />
      )}
    </FormCard>
  );
}
