import type { FieldSelection } from "@/shared/api";
import { projectToBox, type LatLon } from "@/shared/lib";
import { fieldKind, isBuffered } from "../lib/describe";
import s from "./field.module.css";

type SketchProps = {
  /** Polygon rings ([lon, lat] positions); empty for a bare point. */
  rings: readonly (readonly (readonly number[])[])[];
  anchor: LatLon;
  /** Dashed outline: a buffered circle, not a field. */
  dashed: boolean;
  label: string;
  width?: number;
  height?: number;
};

/** A shape drawn from its own geometry (one feature from the API, never bulk GeoJSON). */
export function GeometrySketch({ rings, anchor, dashed, label, width = 220, height = 160 }: SketchProps) {
  const { paths, point } = projectToBox(rings, width, height, 20, anchor);
  const dot = point ?? { x: width / 2, y: height / 2 };
  return (
    <svg viewBox={`0 0 ${width} ${height}`} width={width} height={height} role="img" aria-label={label} className={s.sketch}>
      {paths.length > 0 && <path d={paths.join(" ")} className={dashed ? s.buffer : s.polygon} fillRule="evenodd" />}
      <circle cx={dot.x} cy={dot.y} r={6} className={s.anchor} />
    </svg>
  );
}

/** The selected field. Polygon: solid outline. Buffered circle: dashed, because it is not a field. */
export function FieldSketch({ selection, width, height }: { selection: FieldSelection; width?: number; height?: number }) {
  return (
    <GeometrySketch
      rings={selection.geometry.coordinates}
      anchor={selection.anchor}
      dashed={isBuffered(selection)}
      label={`Sketch of the ${fieldKind(selection).toLowerCase()}`}
      width={width}
      height={height}
    />
  );
}
