import { afterEach, describe, expect, it, vi } from "vitest";
import {
  createPasskey,
  credentialToJSON,
  creationOptionsFromJSON,
  fromBase64url,
  getPasskey,
  passkeysSupported,
  requestOptionsFromJSON,
  toBase64url,
  wasCancelled,
} from "./webauthn";

const bytes = (...b: number[]) => new Uint8Array(b).buffer;
const text = (b: ArrayBuffer | BufferSource | undefined) => Array.from(new Uint8Array(b as ArrayBuffer));

// what py_webauthn's options_to_json sends
const creation = {
  rp: { name: "Yuo", id: "localhost" },
  user: { id: "dXNlcg", name: "learner", displayName: "Learner" },
  challenge: "AQID_-8",
  pubKeyCredParams: [{ type: "public-key", alg: -7 }],
  timeout: 60000,
  excludeCredentials: [{ id: "BAUG", type: "public-key", transports: ["internal"] }],
  authenticatorSelection: { residentKey: "required", userVerification: "preferred" },
  attestation: "none",
};
const request = { challenge: "AQID_-8", timeout: 60000, rpId: "localhost", allowCredentials: [], userVerification: "preferred" };

function fakeCredential(response: object): PublicKeyCredential {
  return {
    id: "BAUG",
    rawId: bytes(4, 5, 6),
    type: "public-key",
    authenticatorAttachment: "platform",
    response,
    getClientExtensionResults: () => ({ credProps: { rk: true } }),
  } as unknown as PublicKeyCredential;
}

const attestation = {
  clientDataJSON: bytes(123, 125),
  attestationObject: bytes(0xa0, 0xff, 0xfe),
  getTransports: () => ["internal", "hybrid"],
};
const assertion = {
  clientDataJSON: bytes(123, 125),
  authenticatorData: bytes(9, 9),
  signature: bytes(0xfb, 0xff),
  userHandle: bytes(117, 115, 101, 114),
};

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("base64url", () => {
  it("round-trips bytes without padding and with the url alphabet", () => {
    const b = bytes(1, 2, 3, 0xff, 0xef);
    expect(toBase64url(b)).toBe("AQID_-8");
    expect(text(fromBase64url("AQID_-8"))).toEqual([1, 2, 3, 0xff, 0xef]);
    expect(toBase64url(new Uint8Array([0xfb, 0xff]))).toBe("-_8");
    expect(toBase64url(new ArrayBuffer(0))).toBe("");
  });
});

describe("options from JSON (fallback)", () => {
  it("turns the creation options' byte fields into buffers and keeps the rest", () => {
    const o = creationOptionsFromJSON(creation);
    expect(text(o.challenge)).toEqual([1, 2, 3, 0xff, 0xef]);
    expect(text(o.user.id)).toEqual([117, 115, 101, 114]);
    expect(o.user.name).toBe("learner");
    expect(text(o.excludeCredentials?.[0]?.id)).toEqual([4, 5, 6]);
    expect(o.excludeCredentials?.[0]?.transports).toEqual(["internal"]);
    expect(o.authenticatorSelection?.residentKey).toBe("required");
    expect(o.rp).toEqual({ name: "Yuo", id: "localhost" });
  });

  it("does the same for request options (discoverable: empty allow list)", () => {
    const o = requestOptionsFromJSON(request);
    expect(text(o.challenge)).toEqual([1, 2, 3, 0xff, 0xef]);
    expect(o.allowCredentials).toEqual([]);
    expect(o.rpId).toBe("localhost");
  });
});

describe("credential to JSON (fallback)", () => {
  it("encodes a registration in the standard JSON form", () => {
    expect(credentialToJSON(fakeCredential(attestation))).toEqual({
      id: "BAUG",
      rawId: "BAUG",
      type: "public-key",
      authenticatorAttachment: "platform",
      clientExtensionResults: { credProps: { rk: true } },
      response: { clientDataJSON: "e30", attestationObject: "oP_-", transports: ["internal", "hybrid"] },
    });
  });

  it("encodes an assertion with the user handle", () => {
    expect(credentialToJSON(fakeCredential(assertion)).response).toEqual({
      clientDataJSON: "e30",
      authenticatorData: "CQk",
      signature: "-_8",
      userHandle: "dXNlcg",
    });
    expect(credentialToJSON(fakeCredential({ ...assertion, userHandle: null })).response).toMatchObject({ userHandle: null });
  });
});

describe("ceremonies", () => {
  it("uses the fallback conversions when the browser has no JSON helpers", async () => {
    vi.stubGlobal("PublicKeyCredential", function PublicKeyCredential() {});
    const create = vi.fn(async () => fakeCredential(attestation));
    const get = vi.fn(async () => fakeCredential(assertion));
    vi.stubGlobal("navigator", { credentials: { create, get }, userAgent: "test" });
    expect(passkeysSupported()).toBe(true);

    const reg = await createPasskey(creation);
    const publicKey = (create.mock.calls[0] as unknown as [{ publicKey: PublicKeyCredentialCreationOptions }])[0].publicKey;
    expect(text(publicKey.challenge)).toEqual([1, 2, 3, 0xff, 0xef]);
    expect(reg).toMatchObject({ rawId: "BAUG", response: { attestationObject: "oP_-" } });

    const auth = await getPasskey(request);
    expect(auth).toMatchObject({ response: { signature: "-_8", userHandle: "dXNlcg" } });
  });

  it("prefers the browser's own parse*FromJSON and toJSON", async () => {
    const parsed = { challenge: bytes(7) };
    const PKC = Object.assign(function PublicKeyCredential() {}, {
      parseCreationOptionsFromJSON: vi.fn(() => parsed),
      parseRequestOptionsFromJSON: vi.fn(() => parsed),
    });
    vi.stubGlobal("PublicKeyCredential", PKC);
    const native = { ...fakeCredential(attestation), toJSON: () => ({ id: "native" }) };
    const create = vi.fn(async () => native);
    vi.stubGlobal("navigator", { credentials: { create, get: create }, userAgent: "test" });

    expect(await createPasskey(creation)).toEqual({ id: "native" });
    expect(PKC.parseCreationOptionsFromJSON).toHaveBeenCalledWith(creation);
    expect(create).toHaveBeenCalledWith({ publicKey: parsed });
    expect(await getPasskey(request)).toEqual({ id: "native" });
    expect(PKC.parseRequestOptionsFromJSON).toHaveBeenCalledWith(request);
  });

  it("reports no passkeys without WebAuthn, and a closed prompt as cancelled", () => {
    vi.stubGlobal("PublicKeyCredential", undefined);
    expect(passkeysSupported()).toBe(false);
    expect(wasCancelled(new DOMException("closed", "NotAllowedError"))).toBe(true);
    expect(wasCancelled(new DOMException("bad", "SecurityError"))).toBe(false);
    expect(wasCancelled(new Error("x"))).toBe(false);
  });
});
