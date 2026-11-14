import type { ButtonHTMLAttributes, ReactNode } from "react";
import { Link, type LinkProps } from "react-router";
import s from "./button.module.css";

export type ButtonVariant = "primary" | "amber" | "secondary" | "ghost" | "link";
export type ButtonSize = "lg" | "md" | "sm";

type StyleProps = {
  variant?: ButtonVariant;
  size?: ButtonSize;
  block?: boolean;
  current?: boolean;
  className?: string;
};

export function buttonClass({ variant = "secondary", size = "sm", block, current, className }: StyleProps) {
  return [s.base, s[size], s[variant], block && s.block, current && s.current, className].filter(Boolean).join(" ");
}

type ButtonProps = StyleProps & ButtonHTMLAttributes<HTMLButtonElement> & { children: ReactNode };

export function Button({ variant, size, block, current, className, type = "button", ...rest }: ButtonProps) {
  return <button type={type} className={buttonClass({ variant, size, block, current, className })} {...rest} />;
}

type ButtonLinkProps = StyleProps & LinkProps;

/** A router link styled as a button (navigation is a link, not a button). */
export function ButtonLink({ variant, size, block, current, className, ...rest }: ButtonLinkProps) {
  return (
    <Link
      className={buttonClass({ variant, size, block, current, className })}
      aria-current={current ? "page" : undefined}
      {...rest}
    />
  );
}
