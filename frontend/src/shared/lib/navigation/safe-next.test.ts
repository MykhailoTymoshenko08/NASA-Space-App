import { safeNext } from "./safe-next";

it.each(["/my-fields", "/account/password", "/field?lat=42&lon=-93#details"])("preserves local return path %s", (path) => {
  expect(safeNext(path)).toBe(path);
});

it.each([null, "", "https://example.com", "//example.com", "/\\example.com", "/\n/example.com", "javascript:alert(1)"])(
  "rejects unsafe return path %s", (path) => { expect(safeNext(path)).toBeNull(); },
);
