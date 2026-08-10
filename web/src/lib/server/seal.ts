const encoder = new TextEncoder();
const decoder = new TextDecoder();
const keys = new Map<string, Promise<CryptoKey>>();

function key(secret: string): Promise<CryptoKey> {
  let pending = keys.get(secret);
  if (!pending) {
    pending = crypto.subtle
      .digest("SHA-256", encoder.encode(`toolgate-console:${secret}`))
      .then((digest) => crypto.subtle.importKey("raw", digest, "AES-GCM", false, ["encrypt", "decrypt"]));
    keys.set(secret, pending);
  }
  return pending;
}

function toBase64Url(bytes: Uint8Array): string {
  let binary = "";
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

function fromBase64Url(text: string): Uint8Array {
  const padded = text.replace(/-/g, "+").replace(/_/g, "/").padEnd(Math.ceil(text.length / 4) * 4, "=");
  const binary = atob(padded);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i += 1) bytes[i] = binary.charCodeAt(i);
  return bytes;
}

/** AES-GCM sealed cookie value: the browser holds it but can neither read nor alter the tokens inside. */
export async function seal(value: unknown, secret: string): Promise<string> {
  const iv = crypto.getRandomValues(new Uint8Array(12));
  const ciphertext = await crypto.subtle.encrypt(
    { name: "AES-GCM", iv },
    await key(secret),
    encoder.encode(JSON.stringify(value)),
  );
  const out = new Uint8Array(iv.length + ciphertext.byteLength);
  out.set(iv);
  out.set(new Uint8Array(ciphertext), iv.length);
  return toBase64Url(out);
}

export async function unseal(sealed: string | undefined, secret: string): Promise<unknown> {
  if (!sealed) return null;
  try {
    const bytes = fromBase64Url(sealed);
    const plaintext = await crypto.subtle.decrypt(
      { name: "AES-GCM", iv: bytes.slice(0, 12) },
      await key(secret),
      bytes.slice(12),
    );
    return JSON.parse(decoder.decode(plaintext)) as unknown;
  } catch {
    return null;
  }
}

export function randomToken(bytes = 32): string {
  return toBase64Url(crypto.getRandomValues(new Uint8Array(bytes)));
}

export async function pkceChallenge(verifier: string): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", encoder.encode(verifier));
  return toBase64Url(new Uint8Array(digest));
}
