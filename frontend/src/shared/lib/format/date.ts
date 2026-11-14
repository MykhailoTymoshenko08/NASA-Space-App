const dateFmt = new Intl.DateTimeFormat("en-US", { month: "short", day: "numeric", year: "numeric", timeZone: "UTC" });
const dateTimeFmt = new Intl.DateTimeFormat("en-US", { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });

/** "Nov 12, 2026" from an API date ("2026-11-12"). Dates are calendar days, so read them as UTC. */
export const formatDate = (isoDate: string) => dateFmt.format(new Date(`${isoDate.slice(0, 10)}T00:00:00Z`));

/** "Nov 14, 3:05 PM" in the reader's time zone, from an API timestamp. */
export const formatDateTime = (isoTimestamp: string) => dateTimeFmt.format(new Date(isoTimestamp));
