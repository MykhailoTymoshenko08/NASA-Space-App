import { useEffect } from "react";
import { useCounties, useStates } from "@/entities/region";
import { friendlyMessage, type County } from "@/shared/api";
import { SelectField } from "@/shared/ui/form";
import s from "./county-picker.module.css";

type Props = {
  stateFips: string | null;
  countyFips: string | null;
  onStateChange: (fips: string) => void;
  onCountyChange: (county: County | null) => void;
  coverageText: string;
};

/**
 * State and county selects from GET /geo/states and /geo/states/{fips}/counties.
 * Picks the first state, then the first county, so the map always has somewhere to go.
 */
export function CountyPicker({ stateFips, countyFips, onStateChange, onCountyChange, coverageText }: Props) {
  const states = useStates();
  const counties = useCounties(stateFips);

  useEffect(() => {
    if (!stateFips && states.data?.[0]) onStateChange(states.data[0].fips);
  }, [stateFips, states.data, onStateChange]);

  useEffect(() => {
    const list = counties.data;
    if (!list || list.length === 0) return;
    const current = list.find((c) => c.fips === countyFips);
    if (!current) onCountyChange(list[0] ?? null);
  }, [counties.data, countyFips, onCountyChange]);

  return (
    <div className={s.wrap}>
      <SelectField
        label="State"
        value={stateFips ?? ""}
        onChange={(e) => onStateChange(e.target.value)}
        disabled={!states.data}
        error={states.isError ? friendlyMessage(states.error) : null}
      >
        {!states.data && <option value="">Loading states…</option>}
        {states.data?.map((st) => (
          <option key={st.fips} value={st.fips}>
            {st.name}
          </option>
        ))}
      </SelectField>
      <SelectField
        label="County"
        value={countyFips ?? ""}
        onChange={(e) => onCountyChange(counties.data?.find((c) => c.fips === e.target.value) ?? null)}
        disabled={!counties.data}
        error={counties.isError ? friendlyMessage(counties.error) : null}
      >
        {!counties.data && <option value="">{stateFips ? "Loading counties…" : "Choose a state first"}</option>}
        {counties.data?.map((c) => (
          <option key={c.fips} value={c.fips}>
            {c.name}
          </option>
        ))}
      </SelectField>
      <p className={s.help}>
        Estimated field areas are available in {coverageText} for now. Elsewhere, paste a link or coordinates. The map
        jumps to the county. Zoom in and pick the field.
      </p>
    </div>
  );
}
