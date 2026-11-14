import { ROUTES } from "@/shared/config";
import { ButtonLink } from "@/shared/ui/button";
import { PagePlaceholder } from "@/shared/ui/placeholder";

export function NotFoundPage() {
  return (
    <PagePlaceholder title="Page not found">
      <p>We couldn't find that page.</p>
      <ButtonLink to={ROUTES.home} variant="secondary" size="md">
        Back to the start
      </ButtonLink>
    </PagePlaceholder>
  );
}
