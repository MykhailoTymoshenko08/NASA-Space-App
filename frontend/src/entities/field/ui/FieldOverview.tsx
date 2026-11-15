import type { FieldSelection } from "@/shared/api";
import { Icon } from "@/shared/ui/icon";
import { MonoLabel } from "@/shared/ui/layout";
import {
  areaText,
  boundaryNote,
  coordsText,
  countyLine,
  cropHistoryLabels,
  fieldKind,
  latestCropText,
} from "../lib/describe";
import { FieldSketch } from "./FieldSketch";
import s from "./field.module.css";

/** Field page head card: sketch, area, county, coordinates, id, mapped crops and the honesty note. */
export function FieldOverview({ selection }: { selection: FieldSelection }) {
  const area = areaText(selection);
  const crops = cropHistoryLabels(selection);
  return (
    <div className={s.overview}>
      <div className={s.overviewSketch}>
        <FieldSketch selection={selection} />
      </div>
      <div className={s.overviewHead}>
        <MonoLabel>{fieldKind(selection)}</MonoLabel>
        {area && <div className={s.bigArea}>{area}</div>}
        <div className={s.countyLine}>{countyLine(selection)}</div>
      </div>
      <div className={s.overviewBody}>
        <dl className={s.factGrid}>
          <div className={s.fact}>
            <dt>Location</dt>
            <dd className={s.coords}>{coordsText(selection)}</dd>
          </div>
          {selection.field_id && (
            <div className={s.fact}>
              <dt>Field ID</dt>
              <dd className={s.fieldId}>{selection.field_id}</dd>
            </div>
          )}
        </dl>
        {crops.length > 0 && (
          <div className={s.crops}>
            <span className={s.muted}>Mapped crops</span>
            {crops.map((c) => (
              <span key={c} className={s.crop}>
                {c}
              </span>
            ))}
          </div>
        )}
        <div className={s.boundaryNote}>
          <Icon name="info" size={20} />
          <span>{boundaryNote(selection)}</span>
        </div>
      </div>
    </div>
  );
}

/** Compact field facts for side panels (pick a field, analysis aside, map card). */
export function FieldFacts({
  selection,
  tone = "plain",
  showNote = true,
  showCrop = true,
}: {
  selection: FieldSelection;
  tone?: "plain" | "wash";
  showNote?: boolean;
  showCrop?: boolean;
}) {
  const area = areaText(selection);
  const crop = showCrop ? latestCropText(selection) : null;
  return (
    <div className={`${s.facts} ${tone === "wash" ? s.factsWash : ""}`}>
      <span className={s.factsTitle}>{fieldKind(selection)}</span>
      <span>{[area && `About ${area}`, countyLine(selection)].filter(Boolean).join(", ")}</span>
      <span className={s.coords}>{coordsText(selection)}</span>
      {selection.field_id && <span className={s.fieldId}>{selection.field_id}</span>}
      {crop && <span>{crop}</span>}
      {showNote && <span className={s.muted}>{boundaryNote(selection)}</span>}
    </div>
  );
}
