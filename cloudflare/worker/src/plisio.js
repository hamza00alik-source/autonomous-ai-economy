/**
 * Verify Plisio's documented non-PHP JSON callback format.
 * Callback URL must include json=true. Preserve received JSON property order:
 * Plisio's Node example signs JSON.stringify(payload without verify_hash)
 * using HMAC-SHA1 and the API secret. This module is not route-wired.
 */
function constantTimeHexEqual(left, right) {
  if (typeof left !== "string" || typeof right !== "string" ||
      !/^[0-9a-f]{40}$/i.test(left) || !/^[0-9a-f]{40}$/i.test(right)) return false;
  let difference = 0;
  const a = left.toLowerCase(), b = right.toLowerCase();
  for (let i = 0; i < 40; i++) difference |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return difference === 0;
}

export async function verifyPlisioJsonCallback(payload, secret) {
  if (!payload || typeof payload !== "object" || Array.isArray(payload) ||
      typeof secret !== "string" || secret.length === 0 ||
      typeof payload.verify_hash !== "string" ||
      !/^[0-9a-f]{40}$/i.test(payload.verify_hash)) return false;

  const unsigned = { ...payload };
  delete unsigned.verify_hash;
  let serialized;
  try { serialized = JSON.stringify(unsigned); } catch { return false; }
  if (typeof serialized !== "string") return false;

  const key = await crypto.subtle.importKey(
    "raw", new TextEncoder().encode(secret),
    { name: "HMAC", hash: "SHA-1" }, false, ["sign"]
  );
  const signature = await crypto.subtle.sign("HMAC", key, new TextEncoder().encode(serialized));
  const expected = [...new Uint8Array(signature)].map(byte => byte.toString(16).padStart(2, "0")).join("");
  return constantTimeHexEqual(expected, payload.verify_hash);
}

export { constantTimeHexEqual };
