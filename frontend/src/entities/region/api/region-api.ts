import { useQuery } from "@tanstack/react-query";
import { api, unwrap } from "@/shared/api";

const DAY = 24 * 60 * 60_000;

/** GET /meta/coverage: map bounds, field tile file and the states with field outlines. */
export function useCoverage() {
  return useQuery({
    queryKey: ["coverage"],
    queryFn: ({ signal }) => unwrap(api.GET("/meta/coverage", { signal })),
    staleTime: DAY,
  });
}

/** GET /geo/states: supported states only, sorted by name. */
export function useStates() {
  return useQuery({
    queryKey: ["geo", "states"],
    queryFn: ({ signal }) => unwrap(api.GET("/geo/states", { signal })).then((r) => r.items),
    staleTime: DAY,
  });
}

/** GET /geo/states/{fips}/counties, sorted by name. */
export function useCounties(stateFips: string | null) {
  return useQuery({
    queryKey: ["geo", "counties", stateFips],
    queryFn: ({ signal }) =>
      unwrap(api.GET("/geo/states/{state_fips}/counties", { params: { path: { state_fips: stateFips! } }, signal })).then(
        (r) => r.items,
      ),
    enabled: stateFips !== null,
    staleTime: DAY,
  });
}

/** GET /geo/counties/{fips}: one county, for its bbox after a map click. */
export function useCounty(countyFips: string | null) {
  return useQuery({
    queryKey: ["geo", "county", countyFips],
    queryFn: ({ signal }) =>
      unwrap(api.GET("/geo/counties/{county_fips}", { params: { path: { county_fips: countyFips! } }, signal })),
    enabled: countyFips !== null,
    staleTime: DAY,
  });
}
