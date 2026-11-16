// The sign-in API (yuo/api/auth.py). These routes are not in the exported OpenAPI document (it is built
// without sign-in), so their shapes are written out here and the calls go through a small fetch helper
// that adds the CSRF header like the generated client does.
import { useMutation, useQuery, useQueryClient, type QueryClient } from "@tanstack/react-query";
import { ApiError, CSRF_HEADER } from "../api/client";
import { deviceLabel } from "./deviceLabel";
import { sessionLost } from "./session";
import { createPasskey, getPasskey, type Json } from "./webauthn";

type AuthMethod = "passkey" | "password";
export type AuthState = {
  signed_in: boolean;
  /** Desktop: starting Yuo from its launcher signs in; there is no passkey or password to set up */
  desktop: boolean;
  enrolled: boolean;
  methods: AuthMethod[];
  device_id: string | null;
  recovery_codes_left: number | null;
};
export type SignedIn = { device_id: string };
export type Options = { challenge_id: string; options: Json };
export type Credential = {
  id: string;
  kind: AuthMethod;
  label: string;
  created_at: string;
  last_used_at: string | null;
};
export type Device = {
  id: string;
  label: string;
  user_agent: string;
  first_seen: string;
  last_seen: string;
  sessions: number;
  current: boolean;
};

/** A refused sign-in step: 400 (wrong code/password, with the server's message) or 429 (throttled). */
export class AuthApiError extends ApiError {
  readonly retryAfter: number | null;

  constructor(status: number, detail: unknown, retryAfter: number | null) {
    super(status, detail);
    this.name = "AuthApiError";
    this.retryAfter = retryAfter;
  }
}

const base = typeof location === "undefined" ? "http://localhost" : location.origin;

export async function authFetch<T>(method: "GET" | "POST" | "PUT" | "DELETE", path: string, body?: unknown): Promise<T> {
  const headers: Record<string, string> = { Accept: "application/json" };
  if (method !== "GET") headers[CSRF_HEADER] = "1";
  if (body !== undefined) headers["Content-Type"] = "application/json";
  const response = await globalThis.fetch(
    new Request(new URL(path, base), {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
      credentials: "same-origin",
    }),
  );
  if (!response.ok) {
    if (response.status === 401) sessionLost();
    let detail: unknown = null;
    try {
      detail = ((await response.json()) as { detail?: unknown }).detail ?? null;
    } catch {
      // no JSON body
    }
    const retry = Number(response.headers.get("Retry-After"));
    throw new AuthApiError(response.status, detail, Number.isFinite(retry) && retry > 0 ? retry : null);
  }
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export const authKeys = {
  state: ["auth", "state"] as const,
  credentials: ["auth", "credentials"] as const,
  devices: ["auth", "devices"] as const,
};

export function useAuthState() {
  return useQuery({
    queryKey: authKeys.state,
    queryFn: () => authFetch<AuthState>("GET", "/api/auth/state"),
    staleTime: 60_000,
    retry: false,
  });
}

/** After a sign-in: forget everything cached for the old session, then load the new state. */
export async function signedIn(qc: QueryClient): Promise<void> {
  qc.removeQueries({ predicate: (q) => q.queryKey[0] !== "auth" });
  await qc.invalidateQueries({ queryKey: ["auth"] });
}

export function useRedeemSetupCode() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (code: string) =>
      authFetch<SignedIn>("POST", "/api/auth/setup", { code, device_label: deviceLabel() }),
    onSuccess: () => signedIn(qc),
  });
}

export function useSignInPassword() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (password: string) =>
      authFetch<SignedIn>("POST", "/api/auth/sign-in/password", { password, device_label: deviceLabel() }),
    onSuccess: () => signedIn(qc),
  });
}

export function useSignInRecovery() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (code: string) =>
      authFetch<SignedIn>("POST", "/api/auth/sign-in/recovery", { code, device_label: deviceLabel() }),
    onSuccess: () => signedIn(qc),
  });
}

export function useSignInPasskey() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async () => {
      const { challenge_id, options } = await authFetch<Options>("POST", "/api/auth/sign-in/passkey/options");
      const credential = await getPasskey(options);
      return authFetch<SignedIn>("POST", "/api/auth/sign-in/passkey", {
        challenge_id,
        credential,
        device_label: deviceLabel(),
      });
    },
    onSuccess: () => signedIn(qc),
  });
}

export function useSignOut() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => authFetch<void>("POST", "/api/auth/sign-out"),
    onSettled: () => {
      qc.removeQueries({ predicate: (q) => q.queryKey[0] !== "auth" });
      qc.setQueryData<AuthState>(authKeys.state, (s) => (s ? { ...s, signed_in: false, device_id: null } : s));
      void qc.invalidateQueries({ queryKey: authKeys.state });
    },
  });
}

export function useAddPasskey() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (label: string) => {
      const { challenge_id, options } = await authFetch<Options>("POST", "/api/auth/passkeys/options");
      const credential = await createPasskey(options);
      return authFetch<Credential>("POST", "/api/auth/passkeys", { challenge_id, credential, label });
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ["auth"] }),
  });
}

export function useSetPassword() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (password: string) => authFetch<void>("PUT", "/api/auth/password", { password }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["auth"] }),
  });
}

export function useNewRecoveryCodes() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => authFetch<{ codes: string[] }>("POST", "/api/auth/recovery-codes"),
    onSuccess: () => qc.invalidateQueries({ queryKey: authKeys.state }),
  });
}

export function useCredentials() {
  return useQuery({
    queryKey: authKeys.credentials,
    queryFn: () => authFetch<Credential[]>("GET", "/api/auth/credentials"),
  });
}

export function useRemoveCredential() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => authFetch<void>("DELETE", `/api/auth/credentials/${encodeURIComponent(id)}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["auth"] }),
  });
}

export function useDevices() {
  return useQuery({
    queryKey: authKeys.devices,
    queryFn: () => authFetch<Device[]>("GET", "/api/auth/devices"),
  });
}

export function useRevokeDevice() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => authFetch<void>("DELETE", `/api/auth/devices/${encodeURIComponent(id)}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: authKeys.devices }),
  });
}
