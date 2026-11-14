/**
 * The access token lives in memory only (never in storage), per the contract's auth rules.
 * The refresh token is an httpOnly cookie the browser sends to /auth/* on its own.
 */
let accessToken: string | null = null;

export const getAccessToken = () => accessToken;

export function setAccessToken(token: string | null) {
  accessToken = token;
}
