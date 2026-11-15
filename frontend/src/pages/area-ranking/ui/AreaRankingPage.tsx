import { useMutation, useQuery } from "@tanstack/react-query";
import { useEffect, useMemo, useState, type FormEvent } from "react";
import { useNavigate } from "react-router";
import { fetchField, selectionSearch } from "@/entities/field";
import { useSavedFieldMutations, useSavedFields } from "@/entities/saved-field";
import { useSession } from "@/entities/session";
import { CountyPicker } from "@/features/pick-by-county";
import { ApiError, api, friendlyMessage, unwrap, type components, type County } from "@/shared/api";
import { fieldPath, ROUTES } from "@/shared/config";
import { formatAcres, useDocumentTitle } from "@/shared/lib";
import { Button, ButtonLink } from "@/shared/ui/button";
import { ErrorPanel, Message } from "@/shared/ui/feedback";
import { Checkbox, SelectField, TextField } from "@/shared/ui/form";
import { Container, PageIntro, Panel } from "@/shared/ui/layout";
import { PickMap } from "@/widgets/pick-map";
import s from "./area-ranking.module.css";

type Request = components["schemas"]["AreaRankingRequest"];
type Filters = NonNullable<Request["filters"]>;

/** County screening, backed by the server's ranking and background soil progress. */
export function AreaRankingPage() {
  useDocumentTitle("Rank fields in an area");
  const session = useSession();
  const userId = session.user?.id ?? null;
  const navigate = useNavigate();
  const saved = useSavedFields(userId);
  const { save } = useSavedFieldMutations(userId);
  const [state, setState] = useState<string | null>(null);
  const [county, setCounty] = useState<County | null>(null);
  const [filters, setFilters] = useState<Filters>({ exclude_continuous_corn: false });
  const [sort, setSort] = useState<"productivity" | "area">("productivity");
  const [minimum, setMinimum] = useState("");
  const [productivity, setProductivity] = useState("");
  const [crop, setCrop] = useState("");
  const [excludeCorn, setExcludeCorn] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [offset, setOffset] = useState(0);
  const [selected, setSelected] = useState<string[]>([]);
  const [active, setActive] = useState<string | null>(null);
  const [cooldown, setCooldown] = useState(false);
  const body = useMemo<Request | null>(() => county ? {
    area: { county_fips: county.fips }, filters, sort, offset, limit: 25, pinned_field_ids: selected,
  } : null, [county, filters, sort, offset, selected]);
  const ranking = useQuery({
    queryKey: ["area-ranking", userId, body],
    queryFn: ({ signal }) => unwrap(api.POST("/comparisons/area", { body: body!, signal })),
    enabled: !!userId && body !== null,
    retry: false,
    refetchOnReconnect: false,
    refetchInterval: (query) => !query.state.error && query.state.data?.soil.status === "filling" ? 5000 : false,
  });
  const retryAfter = ranking.error instanceof ApiError ? ranking.error.retryAfterSeconds : null;
  useEffect(() => {
    if (!retryAfter) { setCooldown(false); return; }
    setCooldown(true);
    const timer = setTimeout(() => setCooldown(false), retryAfter * 1000);
    return () => clearTimeout(timer);
  }, [ranking.error, retryAfter]);
  const field = useQuery({ queryKey: ["ranked-field", active],
    queryFn: ({ signal }) => fetchField(active!, signal), enabled: !!active });
  const compare = useMutation({ mutationFn: async () => {
    const ids: string[] = [];
    for (const id of selected) {
      const existing = saved.data?.items.find((item) => item.field_id === id);
      ids.push(existing?.id ?? (await save.mutateAsync(await fetchField(id))).id);
    }
    navigate(`${ROUTES.myFields}?compare=${encodeURIComponent(ids.join(","))}`);
  } });
  const changeCounty = (next: County | null) => {
    setCounty(next); setOffset(0); setSelected([]); setActive(null); compare.reset();
  };
  const apply = (event: FormEvent) => {
    event.preventDefault();
    const area = minimum.trim() ? Number(minimum) : null;
    const rating = productivity.trim() ? Number(productivity) : null;
    if ((area !== null && (!Number.isFinite(area) || area < 0 || area > 247105)) ||
        (rating !== null && (!Number.isFinite(rating) || rating < 0 || rating > 100))) {
      setError("Enter an area from 0 to 247,105 acres and a productivity rating from 0 to 100."); return;
    }
    setError(null); setOffset(0);
    setFilters({ ...(area !== null ? { min_area_ha: area / 2.4710538147 } : {}),
      ...(rating !== null ? { min_productivity: rating } : {}),
      ...(crop ? { latest_crops: [crop] } : {}), exclude_continuous_corn: excludeCorn });
  };
  const toggle = (id: string) => setSelected((ids) => ids.includes(id)
    ? ids.filter((item) => item !== id) : ids.length < 4 ? [...ids, id] : ids);
  const available = ranking.data ? [...ranking.data.items, ...ranking.data.pinned] : [];
  const pinned = selected.map((id) => available.find((item) => item.field_id === id)).filter((item) => !!item);

  return <>
    <PageIntro title="Rank fields in an area" lead="Screen land by soil productivity, size and crop history. Pick two to four fields to save and compare." />
    <Container className={s.body}>
      {session.status === "unknown" ? <p role="status">Checking your session…</p> : !userId ?
        <Panel><h2>Sign in to rank fields</h2><ButtonLink to={`${ROUTES.signIn}?next=${encodeURIComponent(ROUTES.areaRanking)}`}>Sign in</ButtonLink></Panel> : <>
        <Panel>
          <CountyPicker stateFips={state} countyFips={county?.fips ?? null} coverageText="Iowa, Illinois and Nebraska"
            onStateChange={(next) => { setState(next); changeCounty(null); }} onCountyChange={changeCounty} />
          <form onSubmit={apply}>
            <div className={s.controls}>
              <TextField label="Minimum size (acres)" type="number" min="0" value={minimum} onChange={(e) => setMinimum(e.target.value)} />
              <TextField label="Minimum soil productivity (0–100)" type="number" min="0" max="100" value={productivity} onChange={(e) => setProductivity(e.target.value)} />
              <SelectField label="Last crop" value={crop} onChange={(e) => setCrop(e.target.value)}>
                <option value="">Any crop</option><option value="Corn">Corn</option><option value="Soybeans">Soybeans</option><option value="Winter Wheat">Winter wheat</option>
              </SelectField>
              <SelectField label="Rank by" value={sort} onChange={(e) => { setSort(e.target.value as typeof sort); setOffset(0); }}>
                <option value="productivity">Soil productivity</option><option value="area">Field size</option>
              </SelectField>
            </div>
            <Checkbox checked={excludeCorn} onChange={() => setExcludeCorn((value) => !value)}>Exclude three or more corn years in a row</Checkbox>
            <Button type="submit" disabled={!county || ranking.isFetching || cooldown}>Apply filters</Button>
          </form>
          {error && <Message tone="error" role="alert">{error}</Message>}
          {ranking.isFetching && <p role="status">Reading fields and soil ratings…</p>}
          {ranking.error && <ErrorPanel title="We could not rank this area" message={friendlyMessage(ranking.error)} actions={<Button disabled={cooldown} onClick={() => void ranking.refetch()}>Try again</Button>} />}
        </Panel>
        {ranking.data && <>
          <Panel>
            <h2>{ranking.data.total.toLocaleString()} matching fields</h2>
            <p role="status">Soil ratings: {ranking.data.soil.fields_rated.toLocaleString()} of {ranking.data.soil.fields_total.toLocaleString()} fields. {ranking.data.soil.status === "filling" ? "Loading more ratings; this list updates automatically." : ranking.data.soil.status === "complete" ? "Lookup complete; some soils may have no published rating." : "Some soil ratings are unavailable. You can try again later."}</p>
            <details><summary>Sources and screening limits</summary><p>{ranking.data.soil.method}</p><ul>{ranking.data.notes.map((note) => <li key={note}>{note}</li>)}</ul></details>
            <div className={s.actions}><span>{selected.length} of 4 fields selected</span>
              <Button variant="primary" disabled={selected.length < 2 || compare.isPending || !saved.data} onClick={() => compare.mutate()}>{compare.isPending ? "Saving fields…" : "Save and compare selected fields"}</Button>
            </div>
            {pinned.length > 0 && <p className={s.small}>Selected: {pinned.map((item) => item.field_id).join(", ")}</p>}
            {(compare.error || saved.error) && <Message tone="error" role="alert">{friendlyMessage(compare.error ?? saved.error)}</Message>}
          </Panel>
          {ranking.data.items.length === 0 && <p>No fields match these filters. Try a larger area or fewer filters.</p>}
          <ol className={s.list} start={offset + 1}>
            {ranking.data.items.map((item) => <li className={s.row} key={item.field_id}>
              <strong>#{item.rank ?? "—"} · About {formatAcres(item.area_ha)} acres</strong>
              <span>Soil productivity: {item.productivity === null ? "Not available" : `${item.productivity} / 100`}</span>
              <span className={s.small}>{item.history.latest_crop ?? "Crop history unavailable"}{item.history.latest_year ? ` · ${item.history.latest_year}` : ""}. {item.soil_name ?? "Soil name unavailable"}.</span>
              <span className={s.small}>Size percentile: {item.area_percentile ?? "unavailable"}; soil percentile: {item.productivity_percentile ?? "unavailable"}.</span>
              <Checkbox checked={selected.includes(item.field_id)} disabled={!selected.includes(item.field_id) && selected.length >= 4} onChange={() => toggle(item.field_id)}>Compare field {item.rank ?? item.field_id}</Checkbox>
              <Button variant="secondary" onClick={() => setActive(item.field_id)}>Show field {item.rank ?? ""} on map</Button>
            </li>)}
          </ol>
          <div className={s.actions}>
            <Button disabled={offset === 0 || ranking.isFetching || cooldown} onClick={() => setOffset(Math.max(0, offset - 25))}>Previous page</Button>
            <span>Page {Math.floor(offset / 25) + 1}</span>
            <Button disabled={ranking.data.next_offset === null || ranking.isFetching || cooldown} onClick={() => setOffset(ranking.data!.next_offset!)}>Next page</Button>
          </div>
        </>}
        {county && <>
          {field.error && <Message tone="error" role="alert">{friendlyMessage(field.error)}</Message>}
          {field.data && <div className={s.actions}><ButtonLink to={fieldPath(selectionSearch(field.data))}>Open highlighted field</ButtonLink>
            {field.data.field_id && <Button disabled={selected.includes(field.data.field_id) || selected.length >= 4} onClick={() => toggle(field.data!.field_id!)}>Add highlighted field to comparison</Button>}
          </div>}
          <PickMap stateFips={state} county={county} pin={field.data?.anchor ?? null} selection={field.data ?? null} placeLabel={county.name}
            onSelect={(selection) => { if (selection.field_id) setActive(selection.field_id); }} />
        </>}
      </>}
    </Container>
  </>;
}
