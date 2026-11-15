import { useCounties, useStates } from "@/entities/region";
import { friendlyMessage, type County } from "@/shared/api";
import { SelectField } from "@/shared/ui/form";
import s from "./county-picker.module.css";

type Props = {
  stateFips: string | null;
  countyFips: string | null;
  onStateChange: (fips: string | null) => void;
  onCountyChange: (county: County | null) => void;
  coverageText: string;
};

/**
 * State and county selects from GET /geo/states and /geo/states/{fips}/counties. Nothing is chosen
 * up front: the user picks here or on the map, and both stay in step.
 */
export function CountyPicker({ stateFips, countyFips, onStateChange, onCountyChange, coverageText }: Props) {
  const states = useStates();
  const counties = useCounties(stateFips);

  return (
    <div className={s.wrap}>
      <SelectField
        label="State"
        value={stateFips ?? ""}
        onChange={(e) => onStateChange(e.target.value || null)}
        disabled={!states.data}
        error={states.isError ? friendlyMessage(states.error) : null}
      >
        <option value="">{states.data ? "Choose a state" : "Loading states…"}</option>
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
        <option value="">{!stateFips ? "Choose a state first" : counties.data ? "Choose a county" : "Loading counties…"}</option>
        {counties.data?.map((c) => (
          <option key={c.fips} value={c.fips}>
            {c.name}
          </option>
        ))}
      </SelectField>
      <p className={s.help}>
        Estimated field areas are available in {coverageText} for now. Elsewhere, paste a link or coordinates. You can
        also choose the state and county on the map, then zoom in and pick the field.
      </p>
    </div>
  );
}
