import { api, unwrap } from "@/shared/api";
import { env } from "@/shared/config";

/**
 * Password recovery through our backend. Both real and demo modes use the typed API client;
 * the backend sends reset links through Brevo SMTP without exposing account existence.
 */
export interface PasswordResetApi {
  /** Ask for a reset link by email. Must not reveal whether the account exists. */
  requestLink(email: string): Promise<void>;
  /** Set a new password with the token from the emailed link. */
  setNewPassword(token: string, password: string): Promise<void>;
}

export const passwordResetApi: PasswordResetApi = {
  requestLink: (email) => unwrap(api.POST("/auth/forgot-password", { body: { email } })),
  setNewPassword: (token, password) =>
    unwrap(api.POST("/auth/reset-password", { body: { token, new_password: password }, credentials: "include" })),
};

/** Demo mode shows a button that stands in for clicking the emailed link. */
export const canSimulateEmailLink = () => env.useMocks;
