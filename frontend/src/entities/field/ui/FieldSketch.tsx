import type { FieldSelection } from "@/shared/api";
import { projectToBox } from "@/shared/lib";
import { Skeleton } from "@/shared/ui/feedback";
import { boundaryNote, fieldTitle } from "../lib/describe";
import s from "./field-sketch.module.css";

const W = 320;
const H = 200;

/**
 * The selected field drawn from its own geometry. Neighbours are not drawn:
 * fields come only from vector tiles, never as bulk GeoJSON.
 */
export function FieldSketch({ selection }: { selection: FieldSelection | null }) {
  if (!selection) {
    return (
      <figure className={s.figure}>
        <div className={s.stage}>
          <Skeleton height={H} soft />
        </div>
        <figcaption className={s.caption}>Loading the field outline…</figcaption>
      </figure>
    );
  }

  const { paths, point } = projectToBox(selection.geometry.coordinates, W, H, 24, selection.anchor);
  const buffered = selection.resolved_by === "buffered_point";

  return (
    <figure className={s.figure}>
      <div className={s.stage}>
        <svg viewBox={`0 0 ${W} ${H}`} width="100%" role="img" aria-label={`${fieldTitle(selection)}, drawn as a sketch`}>
          {paths.length > 0 && (
            <path d={paths.join(" ")} className={buffered ? s.buffer : s.field} fillRule="evenodd" />
          )}
          {point && <circle cx={point.x} cy={point.y} r={6} className={s.anchor} />}
        </svg>
      </div>
      <figcaption className={s.caption}>{boundaryNote(selection)}</figcaption>
    </figure>
  );
}
