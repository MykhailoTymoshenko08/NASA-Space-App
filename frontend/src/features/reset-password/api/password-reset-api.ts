import { env } from "@/shared/config";

/**
 * STUB. The contract has no password reset routes yet (design README, open question 2).
 * The screens call only this interface. In demo mode (VITE_USE_MOCKS=1) it pretends to succeed so
 * every state can be reviewed; against a real backend it reports that reset is not available.
 */
export interface PasswordResetApi {
  /** Ask for a reset link by email. Must not reveal whether the account exists. */
  requestLink(email: string): Promise<void>;
  /** Set a new password with the token from the emailed link. */
  setNewPassword(token: string, password: string): Promise<void>;
}

export class ResetUnavailableError extends Error {
  constructor() {
    super("Password reset is not available yet. Please contact us to reset your password.");
    this.name = "ResetUnavailableError";
  }
}

const wait = (ms: number) => new Promise((r) => setTimeout(r, ms));

export const passwordResetApi: PasswordResetApi = {
  async requestLink() {
    if (!env.useMocks) throw new ResetUnavailableError();
    await wait(400);
  },
  async setNewPassword() {
    if (!env.useMocks) throw new ResetUnavailableError();
    await wait(400);
  },
};

/** Demo mode shows a button that stands in for clicking the emailed link. */
export const canSimulateEmailLink = () => env.useMocks;
