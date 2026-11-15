import { useCallback, useState } from "react";
import { FieldFacts, selectionSearch } from "@/entities/field";
import { supportedStatesText, useCoverage } from "@/entities/region";
import { CountyPicker } from "@/features/pick-by-county";
import { LocationInput } from "@/features/pick-by-location";
import { SaveFieldButton } from "@/features/save-field";
import type { County, FieldSelection, ResolvedLocation } from "@/shared/api";
import { analysisSetupPath, fieldPath } from "@/shared/config";
import { useDocumentTitle, type LatLon } from "@/shared/lib";
import { Button, ButtonLink } from "@/shared/ui/button";
import { SegmentedControl } from "@/shared/ui/choice";
import { Icon } from "@/shared/ui/icon";
import { Container, MonoLabel, PageIntro, Panel } from "@/shared/ui/layout";
import { PickMap, type PickMapPlace } from "@/widgets/pick-map";
import s from "./pick-field.module.css";

type Method = "county" | "location";
const SOURCE_LABEL: Record<Method, string> = { county: "County map", location: "Link or coordinates" };

/** Two ways to pick: county (then the map), or one box for a link or coordinates. Both end in a FieldSelection. */
export function PickFieldPage() {
  useDocumentTitle("Pick your field");
  const coverage = useCoverage();
  const [method, setMethod] = useState<Method>("county");
  const [stateFips, setStateFips] = useState<string | null>(null);
  const [county, setCounty] = useState<County | null>(null);
  const [pin, setPin] = useState<LatLon | null>(null);
  const [placeLabel, setPlaceLabel] = useState<string | null>(null);
  const [selection, setSelection] = useState<{ value: FieldSelection; from: Method } | null>(null);

  const switchMethod = (m: Method) => {
    setMethod(m);
    setSelection(null);
    setPin(null);
    setPlaceLabel(null);
  };

  const onStateChange = useCallback((fips: string | null) => {
    setStateFips(fips);
    setCounty(null);
    setSelection(null);
  }, []);
  const onCountyChange = useCallback((c: County | null) => {
    setCounty(c);
    setSelection(null);
  }, []);
  // The map went to a state or county: the lists follow. A selected field stays while the user only zooms
  // out of its county; going to another state or county drops it.
  const onMapPlace = (p: PickMapPlace) => {
    const moved = (p.county !== null && p.county.fips !== county?.fips) || (p.stateFips !== null && p.stateFips !== stateFips);
    setStateFips(p.stateFips);
    setCounty(p.county);
    if (moved) setSelection(null);
  };

  const onResolved = useCallback((r: ResolvedLocation) => {
    setPin(r.point);
    setPlaceLabel(`${r.point.lat.toFixed(4)}, ${r.point.lon.toFixed(4)}`);
    setSelection({ value: r.selection, from: "location" });
  }, []);
  const onCleared = useCallback(() => {
    setPin(null);
    setPlaceLabel(null);
    setSelection(null);
  }, []);

  const sel = selection?.value ?? null;
  const search = sel ? selectionSearch(sel) : "";

  return (
    <>
      <PageIntro
        title="Pick your field"
        lead="Choose how you want to find it. Both ways end in the same place: one estimated field area, ready for analysis."
      />
      <Container className={s.layout}>
        <div className={s.left}>
          <Panel gap={20}>
            <SegmentedControl
              label="How to find your field"
              fill
              value={method}
              onChange={switchMethod}
              options={[
                { value: "county", label: "County", icon: "layers" },
                { value: "location", label: "Link or coordinates", icon: "pin" },
              ]}
            />
            {method === "county" ? (
              <CountyPicker
                stateFips={stateFips}
                countyFips={county?.fips ?? null}
                onStateChange={onStateChange}
                onCountyChange={onCountyChange}
                coverageText={supportedStatesText(coverage.data)}
              />
            ) : (
              <LocationInput onResolved={onResolved} onCleared={onCleared} />
            )}
          </Panel>

          <Panel gap={16} aria-labelledby="selected-title">
            <MonoLabel as="h2" id="selected-title">
              Selected field
            </MonoLabel>
            <div aria-live="polite">
              {sel ? (
                <div className={s.facts}>
                  <FieldFacts selection={sel} />
                  <span className={s.muted}>Picked from: {SOURCE_LABEL[selection!.from]}</span>
                </div>
              ) : (
                <div className={s.none}>No field yet. Choose one on the map and its details appear here.</div>
              )}
            </div>
            <div className={s.actions}>
              {sel ? (
                <>
                  <ButtonLink to={analysisSetupPath(search)} variant="primary" size="lg" block>
                    Get analysis
                    <Icon name="arrow-right" />
                  </ButtonLink>
                  <ButtonLink to={fieldPath(search)} variant="secondary" size="md" block>
                    See base conditions first
                  </ButtonLink>
                  <SaveFieldButton selection={sel} />
                </>
              ) : (
                <>
                  <Button variant="primary" size="lg" block disabled>
                    Get analysis
                  </Button>
                  <Button variant="secondary" size="md" block disabled>
                    See base conditions first
                  </Button>
                </>
              )}
            </div>
            <p className={s.fine}>
              Get analysis compares crop rotations for this field. It supports your decisions and does not replace local
              advice.
            </p>
          </Panel>
        </div>

        <div className={s.right}>
          <PickMap
            // A fresh map per method: a county focus would hide a pasted point, and the other way round.
            key={method}
            stateFips={method === "county" ? stateFips : null}
            county={method === "county" ? county : null}
            pin={pin}
            selection={sel}
            placeLabel={placeLabel}
            onSelect={(value) => setSelection({ value, from: method })}
            onPlaceChange={method === "county" ? onMapPlace : undefined}
          />
        </div>
      </Container>
    </>
  );
}
