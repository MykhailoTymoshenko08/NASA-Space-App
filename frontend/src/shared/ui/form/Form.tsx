import { useId, useState, type InputHTMLAttributes, type ReactNode, type SelectHTMLAttributes } from "react";
import { Icon } from "../icon";
import s from "./form.module.css";

type FieldProps = {
  label: string;
  /** Error under the field (icon + sentence). Sets aria-invalid. */
  error?: string | null;
  /** Help text under the field, read with it by screen readers. */
  hint?: ReactNode;
};

function FieldError({ id, error }: { id: string; error?: string | null }) {
  return (
    <div id={id} aria-live="polite">
      {error && (
        <div className={s.error}>
          <Icon name="warning" size={18} />
          <span>{error}</span>
        </div>
      )}
    </div>
  );
}

const describedBy = (id: string, hint: unknown) => `${id}-msg${hint ? ` ${id}-hint` : ""}`;

type TextFieldProps = FieldProps & Omit<InputHTMLAttributes<HTMLInputElement>, "id">;

/** Label, 48 px input and its own error line (DS "Inputs"). */
export function TextField({ label, error, hint, className, ...input }: TextFieldProps) {
  const id = useId();
  return (
    <div className={`${s.field} ${className ?? ""}`}>
      <label htmlFor={id} className={s.label}>
        {label}
      </label>
      <input
        id={id}
        className={`${s.input} ${error ? s.invalid : ""}`}
        aria-invalid={error ? true : undefined}
        aria-describedby={describedBy(id, hint)}
        {...input}
      />
      {hint && (
        <div id={`${id}-hint`} className={s.hint}>
          {hint}
        </div>
      )}
      <FieldError id={`${id}-msg`} error={error} />
    </div>
  );
}

type PasswordFieldProps = TextFieldProps & { shown?: boolean; onShownChange?: (shown: boolean) => void };

/** Password input with a Show/Hide toggle. Pass `shown` + `onShownChange` to share it with a repeat field. */
export function PasswordField({ label, error, hint, shown, onShownChange, ...input }: PasswordFieldProps) {
  const id = useId();
  const [ownShown, setOwnShown] = useState(false);
  const visible = shown ?? ownShown;
  const toggle = () => (onShownChange ? onShownChange(!visible) : setOwnShown(!visible));
  return (
    <div className={s.field}>
      <label htmlFor={id} className={s.label}>
        {label}
      </label>
      <div className={s.withButton}>
        <input
          id={id}
          type={visible ? "text" : "password"}
          className={`${s.input} ${s.inputPadded} ${error ? s.invalid : ""}`}
          aria-invalid={error ? true : undefined}
          aria-describedby={describedBy(id, hint)}
          {...input}
        />
        <button type="button" className={s.reveal} onClick={toggle} aria-pressed={visible} aria-label="Show password">
          <Icon name="eye" size={18} />
          <span aria-hidden="true">{visible ? "Hide" : "Show"}</span>
        </button>
      </div>
      {hint && (
        <div id={`${id}-hint`} className={s.hint}>
          {hint}
        </div>
      )}
      <FieldError id={`${id}-msg`} error={error} />
    </div>
  );
}

type SelectFieldProps = FieldProps & Omit<SelectHTMLAttributes<HTMLSelectElement>, "id"> & { children: ReactNode };

export function SelectField({ label, error, hint, children, ...select }: SelectFieldProps) {
  const id = useId();
  return (
    <div className={s.field}>
      <label htmlFor={id} className={s.label}>
        {label}
      </label>
      <select
        id={id}
        className={`${s.input} ${s.select} ${error ? s.invalid : ""}`}
        aria-invalid={error ? true : undefined}
        aria-describedby={describedBy(id, hint)}
        {...select}
      >
        {children}
      </select>
      {hint && (
        <div id={`${id}-hint`} className={s.hint}>
          {hint}
        </div>
      )}
      <FieldError id={`${id}-msg`} error={error} />
    </div>
  );
}

/** 22 px checkbox with a 44 px tall label. */
export function Checkbox({
  children,
  className,
  ...input
}: Omit<InputHTMLAttributes<HTMLInputElement>, "type"> & { children: ReactNode }) {
  return (
    <label className={`${s.check} ${className ?? ""}`}>
      <input type="checkbox" className={s.checkBox} {...input} />
      <span>{children}</span>
    </label>
  );
}

/** Error line not tied to one input (icon + sentence). */
export function InlineError({ children, id }: { children: ReactNode; id?: string }) {
  return (
    <div className={s.error} id={id}>
      <Icon name="warning" size={18} />
      <span>{children}</span>
    </div>
  );
}
