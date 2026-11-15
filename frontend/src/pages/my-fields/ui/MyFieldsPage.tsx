import { useState } from "react";
import { useSearchParams } from "react-router";
import { useSavedFieldMutations, useSavedFields } from "@/entities/saved-field";
import { useSession } from "@/entities/session";
import { friendlyMessage } from "@/shared/api";
import { ROUTES } from "@/shared/config";
import { useDocumentTitle } from "@/shared/lib";
import { Button, ButtonLink } from "@/shared/ui/button";
import { ErrorPanel, Message, Skeleton } from "@/shared/ui/feedback";
import { Icon } from "@/shared/ui/icon";
import { Container, PageIntro } from "@/shared/ui/layout";
import { FieldsCompare, MAX_COMPARE, SavedFieldsList } from "@/widgets/saved-fields";
import s from "./my-fields.module.css";

/** "Saved fields" (GET /me/fields) and "Compare fields" (2 to 4). */
export function MyFieldsPage() {
  const session = useSession();
  const userId = session.status === "authenticated" ? session.user.id : null;
  const saved = useSavedFields(userId);
  const { remove, update, refreshInfo } = useSavedFieldMutations(userId);
  // ?compare=id,id opens the comparison directly (used by "Rank fields" after saving the picks).
  const [params] = useSearchParams();
  const [selected, setSelected] = useState<string[]>(() =>
    (params.get("compare") ?? "").split(",").filter(Boolean).slice(0, MAX_COMPARE),
  );
  const [view, setView] = useState<"list" | "compare">(() => (selected.length >= 2 ? "compare" : "list"));

  const fields = saved.data?.items ?? [];
  const chosen = fields.filter((f) => selected.includes(f.id));
  const comparing = view === "compare" && chosen.length >= 2;
  useDocumentTitle(comparing ? "Compare fields" : "Saved fields");

  if (session.status === "unknown") {
    return (
      <Container className={s.pad} role="status">
        <Skeleton height={48} width="40%" />
        <span className="visually-hidden">Checking your session</span>
      </Container>
    );
  }

  if (!userId) {
    return (
      <Container className={s.pad}>
        <div className={s.signedOut}>
          <h1 id="page-title" className={s.h1}>
            Sign in to see your fields
          </h1>
          <p className={s.muted}>Saved fields live in your account, so you can come back to them and compare them.</p>
          <ButtonLink to={`${ROUTES.signIn}?next=${encodeURIComponent(ROUTES.myFields)}`} variant="primary" size="lg" block>
            Sign in
          </ButtonLink>
        </div>
      </Container>
    );
  }

  const toggle = (key: string) =>
    setSelected((list) =>
      list.includes(key) ? list.filter((k) => k !== key) : list.length >= MAX_COMPARE ? list : [...list, key],
    );

  return (
    <>
      <PageIntro
        title={comparing ? "Compare fields" : "Saved fields"}
        lead={
          comparing
            ? "Compare asking rent, illustrative returns and land quality for the fields you picked."
            : "Fields you saved. Select two or more to compare them."
        }
      />
      <Container className={s.body}>
        {saved.isPending && <Skeleton height={200} />}
        {saved.isError && <ErrorPanel title="We could not load your fields" message={friendlyMessage(saved.error)} />}
        {remove.isError && (
          <Message tone="error" role="alert">
            {friendlyMessage(remove.error)}
          </Message>
        )}
        {refreshInfo.isError && (
          <Message tone="error" role="alert">
            {friendlyMessage(refreshInfo.error)}
          </Message>
        )}
        {saved.data &&
          (comparing ? (
            <>
              <div className={s.compareBar}>
                <Button variant="secondary" onClick={() => setView("list")}>
                  <Icon name="arrow-left" size={18} />
                  Back to saved fields
                </Button>
                <span className={s.muted}>Pick 2 to 4 fields. Enter asking rents to compare the same crop plan.</span>
              </div>
              <FieldsCompare key={`${userId}:${chosen.map((field) => field.id).join(",")}`} fields={chosen} userId={userId} />
            </>
          ) : (
            <SavedFieldsList
              fields={fields}
              selected={selected}
              limit={saved.data.limit}
              onToggle={toggle}
              onRemove={(key) => {
                remove.mutate(key);
                setSelected((list) => list.filter((k) => k !== key));
              }}
              onRename={(id, name) => update.mutateAsync({ id, body: { name } })}
              onRefresh={(id) => refreshInfo.mutate(id)}
              refreshingId={refreshInfo.isPending ? (refreshInfo.variables ?? null) : null}
              onCompare={() => setView("compare")}
              removing={remove.isPending}
            />
          ))}
      </Container>
    </>
  );
}
