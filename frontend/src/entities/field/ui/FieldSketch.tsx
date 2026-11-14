import type { FieldSelection } from "@/shared/api";
import { projectToBox } from "@/shared/lib";
import { fieldKind, isBuffered } from "../lib/describe";
import s from "./field.module.css";

/**
 * The selected field drawn from its own geometry (one feature from the API, never bulk GeoJSON).
 * Polygon: solid outline. Buffered circle: dashed outline, because it is not a field.
 */
export function FieldSketch({
  selection,
  width = 220,
  height = 160,
}: {
  selection: FieldSelection;
  width?: number;
  height?: number;
}) {
  const { paths, point } = projectToBox(selection.geometry.coordinates, width, height, 20, selection.anchor);
  const buffered = isBuffered(selection);
  return (
    <svg
      viewBox={`0 0 ${width} ${height}`}
      width={width}
      height={height}
      role="img"
      aria-label={`Sketch of the ${fieldKind(selection).toLowerCase()}`}
      className={s.sketch}
    >
      {paths.length > 0 && (
        <path d={paths.join(" ")} className={buffered ? s.buffer : s.polygon} fillRule="evenodd" />
      )}
      {point && <circle cx={point.x} cy={point.y} r={6} className={s.anchor} />}
    </svg>
  );
}
