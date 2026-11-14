import { env } from "@/shared/config";
import { ButtonLink } from "@/shared/ui/button";
import { PagePlaceholder } from "@/shared/ui/placeholder";

/** Route stub. The pick page (county, map pin, coordinates) is built in a later step. */
export function PickFieldPage() {
  return (
    <PagePlaceholder title="Pick your field">
      <p>Picking a field by county, map pin or coordinates is coming next.</p>
      {env.useMocks && (
        <ButtonLink to="/field?lat=41.5868&lon=-93.625" variant="secondary" size="md">
          Demo: open a sample field
        </ButtonLink>
      )}
    </PagePlaceholder>
  );
}
