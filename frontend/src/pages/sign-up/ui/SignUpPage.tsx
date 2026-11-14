import { useState } from "react";
import { SignUpForm } from "@/features/sign-up";
import type { User } from "@/shared/api";
import { ROUTES } from "@/shared/config";
import { useDocumentTitle } from "@/shared/lib";
import { ButtonLink } from "@/shared/ui/button";
import { Message } from "@/shared/ui/feedback";
import { Icon } from "@/shared/ui/icon";
import { FormCard } from "@/shared/ui/layout";

export function SignUpPage() {
  useDocumentTitle("Create your account");
  const [user, setUser] = useState<User | null>(null);
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
        <SignUpForm onSignedUp={setUser} />
      )}
    </FormCard>
  );
}
