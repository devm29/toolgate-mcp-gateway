import { z } from "zod";

const schema = z.object({
  TOOLGATE_API_ORIGIN: z.string().url().default("http://127.0.0.1:8101"),
  TOOLGATE_PUBLIC_URL: z.string().url().default("http://localhost:8101"),
  TOOLGATE_CONSOLE_URL: z.string().url().default("http://localhost:3101"),
  TOOLGATE_CONSOLE_SESSION_SECRET: z
    .string({ required_error: "TOOLGATE_CONSOLE_SESSION_SECRET is not set" })
    .min(32, "TOOLGATE_CONSOLE_SESSION_SECRET must be at least 32 characters"),
});

export interface ConsoleConfig {
  apiOrigin: string;
  issuer: string;
  consoleUrl: URL;
  sessionSecret: string;
  adminResource: string;
  redirectUri: string;
  allowedHosts: ReadonlySet<string>;
  secureCookies: boolean;
}

export const CONSOLE_CLIENT_ID = "toolgate-console";
export const ADMIN_SCOPE = "toolgate:admin";

let cached: ConsoleConfig | undefined;

export class ConfigError extends Error {}

/** Read lazily so `next build` works without secrets; any request fails loudly instead of using a default. */
export function consoleConfig(): ConsoleConfig {
  if (cached) return cached;
  const parsed = schema.safeParse(process.env);
  if (!parsed.success) {
    throw new ConfigError(parsed.error.issues.map((issue) => issue.message).join("; "));
  }
  const env = parsed.data;
  const consoleUrl = new URL(env.TOOLGATE_CONSOLE_URL);
  const issuer = env.TOOLGATE_PUBLIC_URL.replace(/\/$/, "");
  const loopbackAlias =
    consoleUrl.hostname === "localhost" ? `127.0.0.1:${consoleUrl.port}` : `localhost:${consoleUrl.port}`;
  cached = {
    apiOrigin: env.TOOLGATE_API_ORIGIN.replace(/\/$/, ""),
    issuer,
    consoleUrl,
    sessionSecret: env.TOOLGATE_CONSOLE_SESSION_SECRET,
    adminResource: `${issuer}/api`,
    redirectUri: new URL("/api/auth/callback", consoleUrl).toString(),
    allowedHosts: new Set([consoleUrl.host, ...(isLoopback(consoleUrl.hostname) ? [loopbackAlias] : [])]),
    secureCookies: consoleUrl.protocol === "https:",
  };
  return cached;
}

function isLoopback(hostname: string): boolean {
  return hostname === "localhost" || hostname === "127.0.0.1";
}
