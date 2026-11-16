// Passkeys in the browser (WebAuthn L3 JSON forms). The server sends PublicKeyCredential{Creation,Request}
// Options as JSON with base64url byte fields and expects the credential back in the standard JSON form.
// Browsers with `parse*OptionsFromJSON` and `credential.toJSON()` do the conversion; a small own
// fallback covers the rest. No WebAuthn library: the conversion is all there is to it.

export type Json = Record<string, unknown>;

// --- base64url ---------------------------------------------------------------------------------

export function toBase64url(bytes: ArrayBuffer | ArrayBufferView): string {
  const view =
    bytes instanceof ArrayBuffer ? new Uint8Array(bytes) : new Uint8Array(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  let text = "";
  for (const b of view) text += String.fromCharCode(b);
  return btoa(text).replaceAll("+", "-").replaceAll("/", "_").replace(/=+$/, "");
}

export function fromBase64url(text: string): ArrayBuffer {
  const b64 = text.replaceAll("-", "+").replaceAll("_", "/") + "=".repeat((4 - (text.length % 4)) % 4);
  const raw = atob(b64);
  const out = new Uint8Array(raw.length);
  for (let i = 0; i < raw.length; i++) out[i] = raw.charCodeAt(i);
  return out.buffer;
}

// --- options: JSON -> browser ----------------------------------------------------------------

type Descriptor = { id: string; type: string; transports?: string[] };

function descriptors(list: unknown): PublicKeyCredentialDescriptor[] | undefined {
  if (!Array.isArray(list)) return undefined;
  return (list as Descriptor[]).map((d) => ({
    ...d,
    id: fromBase64url(d.id),
    type: "public-key",
    transports: d.transports as AuthenticatorTransport[] | undefined,
  }));
}

/** Fallback for `PublicKeyCredential.parseCreationOptionsFromJSON`. */
export function creationOptionsFromJSON(json: Json): PublicKeyCredentialCreationOptions {
  const user = json["user"] as { id: string; name: string; displayName: string };
  return {
    ...(json as unknown as PublicKeyCredentialCreationOptions),
    challenge: fromBase64url(json["challenge"] as string),
    user: { ...user, id: fromBase64url(user.id) },
    excludeCredentials: descriptors(json["excludeCredentials"]),
  };
}

/** Fallback for `PublicKeyCredential.parseRequestOptionsFromJSON`. */
export function requestOptionsFromJSON(json: Json): PublicKeyCredentialRequestOptions {
  return {
    ...(json as unknown as PublicKeyCredentialRequestOptions),
    challenge: fromBase64url(json["challenge"] as string),
    allowCredentials: descriptors(json["allowCredentials"]),
  };
}

// --- credential: browser -> JSON ---------------------------------------------------------------

type AttestationLike = AuthenticatorResponse & {
  attestationObject: ArrayBuffer;
  getTransports?: () => string[];
};
type AssertionLike = AuthenticatorResponse & {
  authenticatorData: ArrayBuffer;
  signature: ArrayBuffer;
  userHandle: ArrayBuffer | null;
};

function isAttestation(r: AuthenticatorResponse): r is AttestationLike {
  return "attestationObject" in r;
}

/** Fallback for `credential.toJSON()`: RegistrationResponseJSON or AuthenticationResponseJSON. */
export function credentialToJSON(credential: PublicKeyCredential): Json {
  const r = credential.response;
  const response: Json = { clientDataJSON: toBase64url(r.clientDataJSON) };
  if (isAttestation(r)) {
    response["attestationObject"] = toBase64url(r.attestationObject);
    response["transports"] = typeof r.getTransports === "function" ? r.getTransports() : [];
  } else {
    const a = r as AssertionLike;
    response["authenticatorData"] = toBase64url(a.authenticatorData);
    response["signature"] = toBase64url(a.signature);
    response["userHandle"] = a.userHandle ? toBase64url(a.userHandle) : null;
  }
  const extensions =
    typeof credential.getClientExtensionResults === "function" ? credential.getClientExtensionResults() : {};
  return {
    id: credential.id,
    rawId: toBase64url(credential.rawId),
    type: credential.type,
    response,
    authenticatorAttachment: (credential as { authenticatorAttachment?: string | null }).authenticatorAttachment ?? null,
    clientExtensionResults: extensions,
  };
}

// --- the ceremonies --------------------------------------------------------------------------

type PKCStatic = {
  parseCreationOptionsFromJSON?: (json: Json) => PublicKeyCredentialCreationOptions;
  parseRequestOptionsFromJSON?: (json: Json) => PublicKeyCredentialRequestOptions;
};

function pkc(): PKCStatic | null {
  const ctor = (globalThis as { PublicKeyCredential?: unknown }).PublicKeyCredential;
  return typeof ctor === "function" ? (ctor as PKCStatic) : null;
}

/** True when this browser can make and use passkeys (a secure context with WebAuthn). */
export function passkeysSupported(): boolean {
  return (
    pkc() !== null &&
    typeof navigator !== "undefined" &&
    typeof navigator.credentials?.create === "function" &&
    (globalThis as { isSecureContext?: boolean }).isSecureContext !== false
  );
}

function toJSON(credential: PublicKeyCredential): Json {
  const native = (credential as { toJSON?: () => unknown }).toJSON;
  if (typeof native === "function") {
    try {
      return native.call(credential) as Json;
    } catch {
      // some builds throw for extension results they cannot serialise: use our own form
    }
  }
  return credentialToJSON(credential);
}

/** Creates a passkey from the server's creation options; returns the credential as JSON. */
export async function createPasskey(options: Json): Promise<Json> {
  const P = pkc();
  const publicKey =
    typeof P?.parseCreationOptionsFromJSON === "function"
      ? P.parseCreationOptionsFromJSON(options)
      : creationOptionsFromJSON(options);
  const credential = (await navigator.credentials.create({ publicKey })) as PublicKeyCredential | null;
  if (!credential) throw new DOMException("no credential", "NotAllowedError");
  return toJSON(credential);
}

/** Signs in with a passkey (discoverable: the browser offers the passkeys it has for this site). */
export async function getPasskey(options: Json): Promise<Json> {
  const P = pkc();
  const publicKey =
    typeof P?.parseRequestOptionsFromJSON === "function"
      ? P.parseRequestOptionsFromJSON(options)
      : requestOptionsFromJSON(options);
  const credential = (await navigator.credentials.get({ publicKey })) as PublicKeyCredential | null;
  if (!credential) throw new DOMException("no credential", "NotAllowedError");
  return toJSON(credential);
}

/** The prompt was closed, timed out or refused (the learner can just try again). */
export function wasCancelled(error: unknown): boolean {
  return error instanceof DOMException && (error.name === "NotAllowedError" || error.name === "AbortError");
}
