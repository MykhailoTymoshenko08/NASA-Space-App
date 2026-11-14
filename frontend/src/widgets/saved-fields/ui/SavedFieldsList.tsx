import { Link } from "react-router";
import { GeometrySketch } from "@/entities/field";
import type { SavedField } from "@/entities/saved-field";
import { fieldPath, ROUTES } from "@/shared/config";
import { formatAcres } from "@/shared/lib";
import { Button, ButtonLink, buttonClass } from "@/shared/ui/button";
import { Checkbox } from "@/shared/ui/form";
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
  onCompare: () => void;
  removing: boolean;
};

/** "My fields" (GET /me/fields): cards with a sketch, compare checkboxes (2 to 4), open and remove. */
export function SavedFieldsList({ fields, selected, limit, onToggle, onRemove, onCompare, removing }: Props) {
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
                <div className={s.titleRow}>
                  <h2 className={s.title}>{f.name}</h2>
                  {f.area_ha != null && <div className={s.muted}>About {formatAcres(f.area_ha)} acres</div>}
                </div>
                <div className={s.muted}>
                  {savedKind(f)}, {f.state}. {crop ? `Latest crop: ${crop}` : "No crop recorded"}
                </div>
                <div className={s.coords}>{savedCoords(f)}</div>
                {f.field_id && <div className={s.id}>{f.field_id}</div>}
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
