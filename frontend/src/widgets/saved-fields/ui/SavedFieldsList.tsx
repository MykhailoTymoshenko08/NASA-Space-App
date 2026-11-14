import { useState, type FormEvent } from "react";
import { Link } from "react-router";
import { GeometrySketch } from "@/entities/field";
import { nameError, type SavedField } from "@/entities/saved-field";
import { friendlyMessage } from "@/shared/api";
import { fieldPath, ROUTES } from "@/shared/config";
import { formatAcres, formatDateTime } from "@/shared/lib";
import { Button, ButtonLink, buttonClass } from "@/shared/ui/button";
import { Checkbox, TextField } from "@/shared/ui/form";
import { Icon } from "@/shared/ui/icon";
import { isPoint, savedCoords, savedCrop, savedKind, savedRings, savedSearch } from "../lib/title";
import s from "./saved-fields.module.css";

export const MAX_COMPARE = 4;

type Props = {
  fields: readonly SavedField[];
  /** Saved field ids picked for comparison. */
  selected: readonly string[];
  limit: number;
  onToggle: (id: string) => void;
  onRemove: (id: string) => void;
  /** PATCH /me/fields/{id} with a new name. Rejects with the API error. */
  onRename: (id: string, name: string) => Promise<unknown>;
  /** POST /me/fields/{id}/refresh-info. */
  onRefresh: (id: string) => void;
  /** Saved field whose data is being fetched again, if any. */
  refreshingId: string | null;
  onCompare: () => void;
  removing: boolean;
};

/** Inline rename form for one card. */
function RenameForm({ field, onRename, onDone }: { field: SavedField; onRename: Props["onRename"]; onDone: () => void }) {
  const [name, setName] = useState(field.name);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    const problem = nameError(name);
    if (problem) return setError(problem);
    if (name.trim() === field.name) return onDone();
    setBusy(true);
    setError(null);
    try {
      await onRename(field.id, name.trim());
      onDone();
    } catch (err) {
      setError(friendlyMessage(err));
      setBusy(false);
    }
  };

  return (
    <form className={s.rename} onSubmit={submit} noValidate>
      <TextField
        label="Field name"
        value={name}
        maxLength={100}
        autoFocus
        error={error}
        onChange={(e) => setName(e.target.value)}
        onKeyDown={(e) => e.key === "Escape" && onDone()}
      />
      <div className={s.right}>
        <Button type="submit" variant="primary" disabled={busy}>
          {busy ? "Saving..." : "Save name"}
        </Button>
        <Button variant="ghost" onClick={onDone} disabled={busy}>
          Cancel
        </Button>
      </div>
    </form>
  );
}

/** "My fields" (GET /me/fields): cards with a sketch, compare checkboxes (2 to 4), open and remove. */
export function SavedFieldsList({
  fields,
  selected,
  limit,
  onToggle,
  onRemove,
  onRename,
  onRefresh,
  refreshingId,
  onCompare,
  removing,
}: Props) {
  const [editingId, setEditingId] = useState<string | null>(null);
  if (fields.length === 0) {
    return (
      <div className={s.empty}>
        <div className={s.emptyTitle}>No saved fields yet</div>
        <p className={s.muted}>Pick a field, then press Save field. It will show up here and you can compare it with others.</p>
        <ButtonLink to={ROUTES.pickField} variant="primary" size="lg" className={s.emptyCta}>
          Pick a field
        </ButtonLink>
      </div>
    );
  }

  const n = selected.length;
  return (
    <>
      <div className={s.selBar}>
        <div aria-live="polite">
          <div className={s.selText}>{n === 0 ? "No fields selected" : n === 1 ? "1 field selected" : `${n} fields selected`}</div>
          <div className={s.muted}>
            {n >= MAX_COMPARE ? "You can compare up to 4 fields at once." : "Select 2 to 4 fields with the Compare checkboxes."}{" "}
            {fields.length} of {limit} saved.
          </div>
        </div>
        <Button variant="primary" size="lg" onClick={onCompare} disabled={n < 2}>
          <Icon name="columns" />
          Compare fields
        </Button>
      </div>

      <ul className={s.grid}>
        {fields.map((f) => {
          const on = selected.includes(f.id);
          const crop = savedCrop(f);
          return (
            <li key={f.id} className={`${s.card} ${on ? s.cardOn : ""}`}>
              <div className={s.sketch}>
                <GeometrySketch
                  rings={savedRings(f)}
                  anchor={f.centroid}
                  dashed={isPoint(f)}
                  label={`Sketch of ${f.name}`}
                  width={240}
                  height={120}
                />
              </div>
              <div className={s.body}>
                {editingId === f.id ? (
                  <RenameForm field={f} onRename={onRename} onDone={() => setEditingId(null)} />
                ) : (
                  <div className={s.titleRow}>
                    <h2 className={s.title}>{f.name}</h2>
                    {f.area_ha != null && <div className={s.muted}>About {formatAcres(f.area_ha)} acres</div>}
                  </div>
                )}
                <div className={s.muted}>
                  {savedKind(f)}, {f.state}. {crop ? `Latest crop: ${crop}` : "No crop recorded"}
                </div>
                <div className={s.coords}>{savedCoords(f)}</div>
                {f.field_id && <div className={s.id}>{f.field_id}</div>}
                <div className={s.small}>
                  {f.info_fetched_at ? `Field data from ${formatDateTime(f.info_fetched_at)}.` : "No field data stored yet."}{" "}
                  <button
                    type="button"
                    className={s.linkButton}
                    onClick={() => onRefresh(f.id)}
                    disabled={refreshingId !== null}
                  >
                    {refreshingId === f.id ? "Refreshing..." : "Refresh data"}
                  </button>
                </div>
                <div className={s.actions}>
                  <Checkbox
                    checked={on}
                    disabled={!on && n >= MAX_COMPARE}
                    onChange={() => onToggle(f.id)}
                    aria-label={`Compare ${f.name}`}
                  >
                    Compare
                  </Checkbox>
                  <div className={s.right}>
                    <Link to={fieldPath(savedSearch(f))} className={buttonClass({ variant: "secondary" })}>
                      Open
                    </Link>
                    <button
                      type="button"
                      className={s.remove}
                      onClick={() => setEditingId(f.id)}
                      disabled={editingId === f.id}
                      aria-label={`Rename ${f.name}`}
                    >
                      <Icon name="file" />
                    </button>
                    <button
                      type="button"
                      className={s.remove}
                      onClick={() => onRemove(f.id)}
                      disabled={removing}
                      aria-label={`Remove ${f.name} from saved fields`}
                    >
                      <Icon name="trash" />
                    </button>
                  </div>
                </div>
              </div>
            </li>
          );
        })}
      </ul>
    </>
  );
}
