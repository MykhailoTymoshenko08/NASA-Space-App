import { Link, useLocation } from "react-router";
import { matchesSelection, useSavedFieldMutations, useSavedFields } from "@/entities/saved-field";
import { useSession } from "@/entities/session";
import { friendlyMessage, type FieldSelection } from "@/shared/api";
import { ROUTES } from "@/shared/config";
import { Button, buttonClass } from "@/shared/ui/button";
import { Message } from "@/shared/ui/feedback";
import { Icon } from "@/shared/ui/icon";
import s from "./save-field.module.css";

/**
 * "Save field" toggle for signed-in users; "Sign in to save this field" otherwise.
 * POST /me/fields to save, DELETE /me/fields/{id} to unsave.
 */
export function SaveFieldButton({
  selection,
  showMyFieldsLink = false,
}: {
  selection: FieldSelection;
  showMyFieldsLink?: boolean;
}) {
  const session = useSession();
  const here = useLocation();
  const userId = session.status === "authenticated" ? session.user.id : null;
  const saved = useSavedFields(userId);
  const { save, remove } = useSavedFieldMutations(userId);
  const match = saved.data?.items.find((f) => matchesSelection(f, selection)) ?? null;
  const isSaved = match !== null;

  if (session.status === "unknown") return null;
  if (!userId) {
    return (
      <Link
        to={`${ROUTES.signIn}?next=${encodeURIComponent(here.pathname + here.search)}`}
        className={buttonClass({ variant: "secondary", size: "md", block: true })}
      >
        <Icon name="bookmark" />
        Sign in to save this field
      </Link>
    );
  }

  const pending = save.isPending || remove.isPending;
  const toggle = () => {
    if (!saved.isSuccess || saved.isFetching) return;
    if (match) remove.mutate(match.id);
    else save.mutate(selection);
  };
  const error = saved.error ?? save.error ?? remove.error;

  return (
    <>
      <Button
        variant="secondary"
        size="md"
        block
        aria-pressed={isSaved}
        onClick={toggle}
        disabled={pending || !saved.isSuccess || saved.isFetching}
        className={isSaved ? s.saved : undefined}
      >
        <Icon name="bookmark" filled={isSaved} />
        {isSaved ? "Saved" : "Save field"}
      </Button>
      {error && (
        <Message tone="error" role="alert">
          {friendlyMessage(error)}
        </Message>
      )}
      {saved.isError && (
        <Button variant="ghost" onClick={() => void saved.refetch()} disabled={saved.isFetching}>
          {saved.isFetching ? "Checking saved fields…" : "Retry saved fields"}
        </Button>
      )}
      {showMyFieldsLink && isSaved && (
        <Link to={ROUTES.myFields} className={s.link}>
          See my saved fields
        </Link>
      )}
    </>
  );
}
