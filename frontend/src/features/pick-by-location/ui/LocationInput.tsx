import { useEffect, useRef, useState } from "react";
import { api, unwrap, type ResolvedLocation } from "@/shared/api";
import { Message } from "@/shared/ui/feedback";
import { TextField } from "@/shared/ui/form";
import { errorMessage, isShortLink, resolvedMessage, type LocationMessage } from "../model/location-message";
import s from "./location-input.module.css";

const DEBOUNCE_MS = 700;

/**
 * One box for a Google Maps link, an Apple Maps link or coordinates.
 * The backend parses it (POST /locations/resolve); we only debounce and show the result.
 */
export function LocationInput({
  initialText = "",
  onResolved,
  onCleared,
}: {
  initialText?: string;
  onResolved: (r: ResolvedLocation, input: string) => void;
  onCleared: () => void;
}) {
  const [text, setText] = useState(initialText);
  const [msg, setMsg] = useState<LocationMessage | null>(null);
  const [pending, setPending] = useState(false);
  const seq = useRef(0);
  const callbacks = useRef({ onResolved, onCleared });
  callbacks.current = { onResolved, onCleared };

  useEffect(() => {
    const input = text.trim();
    const id = ++seq.current;
    callbacks.current.onCleared();
    setMsg(null);
    setPending(false);
    if (input.length < 3) {
      return;
    }
    const controller = new AbortController();
    const timer = setTimeout(async () => {
      setPending(true);
      setMsg(
        isShortLink(input)
          ? { tone: "info", text: "This is a short link. We open it on our server to read the pin, then show the map." }
          : null,
      );
      try {
        const r = await unwrap(api.POST("/locations/resolve", { body: { input }, signal: controller.signal }));
        if (id !== seq.current) return;
        setMsg(resolvedMessage(r));
        callbacks.current.onResolved(r, input);
      } catch (err) {
        if (id !== seq.current || controller.signal.aborted) return;
        setMsg(errorMessage(err));
        callbacks.current.onCleared();
      } finally {
        if (id === seq.current) setPending(false);
      }
    }, DEBOUNCE_MS);
    return () => {
      clearTimeout(timer);
      controller.abort();
    };
  }, [text]);

  const isError = msg?.tone === "error";

  return (
    <div className={s.wrap}>
      <TextField
        label="Google Maps link, Apple Maps link or coordinates"
        value={text}
        onChange={(e) => setText(e.target.value)}
        maxLength={2048}
        placeholder="41.5868, -93.6250 or paste a link"
        autoComplete="off"
        spellCheck={false}
        aria-busy={pending}
        aria-invalid={isError || undefined}
        className={isError ? s.invalid : undefined}
      />
      <ul className={s.tips}>
        <li>Coordinates: latitude first, as decimals or degrees, minutes and seconds.</li>
        <li>Google Maps: press and hold on the field, then copy the link from Share.</li>
        <li>Apple Maps: drop a pin, tap Share, then Copy Link.</li>
      </ul>
      <div aria-live="polite">
        {pending && !msg && <p className={s.pending}>Looking up that location…</p>}
        {msg && (
          <Message tone={msg.tone} role="status">
            {msg.text}
          </Message>
        )}
      </div>
    </div>
  );
}
