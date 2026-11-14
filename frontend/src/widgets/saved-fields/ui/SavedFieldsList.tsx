import { Link } from "react-router";
import { areaText, coordsText, FieldSketch, isBuffered, selectionSearch } from "@/entities/field";
import type { SavedField } from "@/entities/saved-field";
import { fieldPath, ROUTES } from "@/shared/config";
import { Button, ButtonLink, buttonClass } from "@/shared/ui/button";
import { Checkbox } from "@/shared/ui/form";
import { Icon } from "@/shared/ui/icon";
import { savedTitle } from "../lib/title";
import s from "./saved-fields.module.css";

export const MAX_COMPARE = 4;

type Props = {
  fields: readonly SavedField[];
  selected: readonly string[];
  onToggle: (key: string) => void;
  onRemove: (key: string) => void;
  onCompare: () => void;
  removing: boolean;
};

/** "My fields": cards with a sketch, compare checkboxes (2 to 4), open and remove. */
export function SavedFieldsList({ fields, selected, onToggle, onRemove, onCompare, removing }: Props) {
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
            {n >= MAX_COMPARE ? "You can compare up to 4 fields at once." : "Select 2 to 4 fields with the Compare checkboxes."}
          </div>
        </div>
        <Button variant="primary" size="lg" onClick={onCompare} disabled={n < 2}>
          <Icon name="columns" />
          Compare fields
        </Button>
      </div>

      <ul className={s.grid}>
        {fields.map((f) => {
          const on = selected.includes(f.key);
          const title = savedTitle(f.selection);
          const area = areaText(f.selection);
          return (
            <li key={f.key} className={`${s.card} ${on ? s.cardOn : ""}`}>
              <div className={s.sketch}>
                <FieldSketch selection={f.selection} width={240} height={120} />
              </div>
              <div className={s.body}>
                <div className={s.titleRow}>
                  <h2 className={s.title}>{title}</h2>
                  {area && <div className={s.muted}>About {area.split(" (")[0]}</div>}
                </div>
                <div className={s.muted}>
                  {isBuffered(f.selection) ? "Circle around a point" : "Estimated field area"}.{" "}
                  {f.selection.crop_class ? `Mapped crop: ${f.selection.crop_class}` : "No crop mapped"}
                </div>
                <div className={s.coords}>{coordsText(f.selection)}</div>
                <div className={s.id}>{f.selection.field_id ?? "Circle around a point, no field outline"}</div>
                <div className={s.actions}>
                  <Checkbox
                    checked={on}
                    disabled={!on && n >= MAX_COMPARE}
                    onChange={() => onToggle(f.key)}
                    aria-label={`Compare ${title}`}
                  >
                    Compare
                  </Checkbox>
                  <div className={s.right}>
                    <Link to={fieldPath(selectionSearch(f.selection))} className={buttonClass({ variant: "secondary" })}>
                      Open
                    </Link>
                    <button
                      type="button"
                      className={s.remove}
                      onClick={() => onRemove(f.key)}
                      disabled={removing}
                      aria-label={`Remove ${title} from saved fields`}
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
