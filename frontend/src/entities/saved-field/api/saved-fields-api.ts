import type { FieldSelection } from "@/shared/api";

/**
 * STUB. The contract has no saved-fields endpoints yet (design README, open question 1).
 * Everything goes through this interface, so swapping in the real endpoints later touches
 * only `savedFieldsApi` below. Until then fields are kept in this browser, per signed-in user.
 */
export type SavedField = {
  /** field_id, or "pt:lat,lon" for a buffered point. */
  key: string;
  selection: FieldSelection;
  savedAt: string;
  /** Best-fit rotation from the last analysis seen for this field, if any. */
  bestRotation: { name: string; score: number } | null;
};

export interface SavedFieldsApi {
  list(userId: string): Promise<SavedField[]>;
  save(userId: string, field: Omit<SavedField, "savedAt">): Promise<void>;
  remove(userId: string, key: string): Promise<void>;
  setBestRotation(userId: string, key: string, best: SavedField["bestRotation"]): Promise<void>;
}

const storageKey = (userId: string) => `fieldline.saved.${userId}`;

function read(userId: string): SavedField[] {
  try {
    const raw = localStorage.getItem(storageKey(userId));
    const parsed: unknown = raw ? JSON.parse(raw) : [];
    return Array.isArray(parsed) ? (parsed as SavedField[]) : [];
  } catch {
    return [];
  }
}

function write(userId: string, list: SavedField[]) {
  try {
    localStorage.setItem(storageKey(userId), JSON.stringify(list));
  } catch {
    throw new Error("We could not save this field in your browser. Check that site storage is allowed.");
  }
}

/** Browser-only stand-in for the missing endpoints. */
export const browserSavedFieldsApi: SavedFieldsApi = {
  async list(userId) {
    return read(userId).sort((a, b) => b.savedAt.localeCompare(a.savedAt));
  },
  async save(userId, field) {
    const list = read(userId).filter((f) => f.key !== field.key);
    write(userId, [{ ...field, savedAt: new Date().toISOString() }, ...list]);
  },
  async remove(userId, key) {
    write(
      userId,
      read(userId).filter((f) => f.key !== key),
    );
  },
  async setBestRotation(userId, key, best) {
    const list = read(userId);
    if (!list.some((f) => f.key === key)) return;
    write(
      userId,
      list.map((f) => (f.key === key ? { ...f, bestRotation: best } : f)),
    );
  },
};

/** The implementation the app uses. Replace with an HTTP client once the contract has the endpoints. */
export const savedFieldsApi: SavedFieldsApi = browserSavedFieldsApi;
