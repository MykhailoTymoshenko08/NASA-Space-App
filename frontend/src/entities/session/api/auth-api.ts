import { api, unwrap, type AuthTokens, type User } from "@/shared/api";

/** The refresh token is an httpOnly cookie on /v1/auth, so every auth call sends credentials. */
const withCookie = { credentials: "include" } as const;

export const authApi = {
  login: (email: string, password: string) =>
    unwrap<AuthTokens>(api.POST("/auth/login", { body: { email, password }, ...withCookie })),
  register: (email: string, password: string) =>
    unwrap<AuthTokens>(api.POST("/auth/register", { body: { email, password }, ...withCookie })),
  refresh: () => unwrap<AuthTokens>(api.POST("/auth/refresh", withCookie)),
  logout: () => unwrap(api.POST("/auth/logout", withCookie)),
  me: () => unwrap<User>(api.GET("/me")),
};
