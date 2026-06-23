/**
 * Visitor counter Worker for wc2026.rearyan.com
 *
 * Setup (in the Cloudflare dashboard):
 *  1. Workers & Pages -> Create -> Worker. Name it e.g. "wc2026-counter". Deploy.
 *  2. Storage & Databases -> KV -> Create namespace, name it "wc2026_counter".
 *  3. Back in the Worker -> Settings -> Variables -> KV Namespace Bindings ->
 *     Add binding. Variable name MUST be exactly: COUNTER
 *     Namespace: wc2026_counter. Save.
 *  4. Edit the Worker code (paste this file) and Deploy.
 *  5. Note the Worker URL (like https://wc2026-counter.<you>.workers.dev).
 *     Put that URL into index.html where COUNTER_URL is defined.
 *
 * Endpoints:
 *   GET /         -> increments once per visit, returns {"count": N}
 *   GET /?peek=1  -> returns the current count WITHOUT incrementing
 *
 * CORS is open so the static site can read it from any origin.
 */

export default {
  async fetch(request, env) {
    const cors = {
      "Access-Control-Allow-Origin": "*",
      "Access-Control-Allow-Methods": "GET, OPTIONS",
      "Cache-Control": "no-store",
      "Content-Type": "application/json",
    };

    if (request.method === "OPTIONS") {
      return new Response(null, { headers: cors });
    }

    // Guard: if the KV binding is missing, fail soft so the page just hides the counter.
    if (!env.COUNTER) {
      return new Response(JSON.stringify({ error: "no_kv" }), { status: 200, headers: cors });
    }

    const url = new URL(request.url);
    const peek = url.searchParams.get("peek") === "1";

    let count = parseInt((await env.COUNTER.get("total")) || "0", 10);
    if (Number.isNaN(count)) count = 0;

    if (!peek) {
      count += 1;
      // best-effort write; if it fails we still return the incremented number
      await env.COUNTER.put("total", String(count));
    }

    return new Response(JSON.stringify({ count }), { headers: cors });
  },
};
