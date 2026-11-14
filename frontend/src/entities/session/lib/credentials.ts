/** Client-side checks that mirror the contract (RegisterRequest), so users see problems before sending. */
export const isEmail = (v: string) => /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(v.trim());

export const emailError = (v: string) =>
  isEmail(v) ? null : v.trim() ? "Enter an email like name@example.com." : "Enter your email.";

export type PasswordRule = { id: string; text: string; ok: boolean };

/** RegisterRequest.password: 8 to 128 characters, at least one letter and one digit. */
export function passwordRules(pw: string): PasswordRule[] {
  return [
    { id: "length", text: "at least 8 characters", ok: pw.length >= 8 && pw.length <= 128 },
    { id: "letter", text: "at least one letter", ok: /\p{L}/u.test(pw) },
    { id: "number", text: "at least one number", ok: /\d/.test(pw) },
  ];
}

export const passwordOk = (pw: string) => passwordRules(pw).every((r) => r.ok);
