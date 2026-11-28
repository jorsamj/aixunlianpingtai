export async function sha256Bytes(bytes: ArrayBuffer) {
  const subtle = globalThis.crypto?.subtle;
  if (subtle) return new Uint8Array(await subtle.digest('SHA-256', bytes));
  const {sha256} = await import('@noble/hashes/sha2.js');
  return sha256(new Uint8Array(bytes));
}

export function digestHex(bytes: Uint8Array) {
  return Array.from(bytes, byte => byte.toString(16).padStart(2, '0')).join('');
}
