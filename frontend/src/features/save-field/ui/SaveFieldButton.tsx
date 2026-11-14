import { Link, useLocation } from "react-router";
import { selectionKey } from "@/entities/field";
import { useSavedFieldMutations, useSavedFields, type SavedField } from "@/entities/saved-field";
import { useSession } from "@/entities/session";
import type { FieldSelection } from "@/shared/api";
import { ROUTES } from "@/shared/config";
import { Button, buttonClass } from "@/shared/ui/button";
import { Message } from "@/shared/ui/feedback";
import { Icon } from "@/shared/ui/icon";
import s from "./save-field.module.css";

/**
 * "Save field" toggle for signed-in users; "Sign in to save this field" otherwise.
 * Saved fields go through the saved-field entity (a stub until the contract has endpoints).
 */
export function SaveFieldButton({
  selection,
  bestRotation,
  showMyFieldsLink = false,
}: {
  selection: FieldSelection;
  bestRotation?: SavedField["bestRotation"];
  showMyFieldsLink?: boolean;
}) {
  const session = useSession();
  const here = useLocation();
  const userId = session.status === "authenticated" ? session.user.id : null;
  const saved = useSavedFields(userId);
  const { save, remove } = useSavedFieldMutations(userId);
  const key = selectionKey(selection);
  const isSaved = saved.data?.some((f) => f.key === key) ?? false;

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
  const toggle = () => (isSaved ? remove.mutate(key) : save.mutate({ key, selection, bestRotation: bestRotation ?? null }));
  const error = save.error ?? remove.error;

  return (
    <>
      <Button
        variant="secondary"
        size="md"
        block
        aria-pressed={isSaved}
        onClick={toggle}
        disabled={pending || saved.isPending}
        className={isSaved ? s.saved : undefined}
      >
        <Icon name="bookmark" filled={isSaved} />
        {isSaved ? "Saved" : "Save field"}
      </Button>
      {error && (
        <Message tone="error" role="alert">
          {error instanceof Error ? error.message : "We could not save this field."}
        </Message>
      )}
      {showMyFieldsLink && isSaved && (
        <Link to={ROUTES.myFields} className={s.link}>
          See my saved fields
        </Link>
      )}
    </>
  );
}
