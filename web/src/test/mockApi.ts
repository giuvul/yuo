import { vi } from "vitest";

export type Handler = (request: Request, body: unknown) => Response | "network-error" | Promise<Response | "network-error">;
export type Call = { method: string; path: string; body: unknown };

export function json(data: unknown, status = 200): Response {
  return new Response(JSON.stringify(data), { status, headers: { "Content-Type": "application/json" } });
}

/**
 * Stubs globalThis.fetch with a table of "METHOD /path" handlers (path without the query string).
 * Unmatched requests answer 404 so a missing handler shows up as a failing assertion, not a hang.
 */
export function mockApi(routes: Record<string, Handler>) {
  const calls: Call[] = [];
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const request = input instanceof Request ? input : new Request(input, init);
    const url = new URL(request.url);
    const text = request.method === "GET" ? "" : await request.clone().text();
    const body = text ? (JSON.parse(text) as unknown) : undefined;
    const key = `${request.method} ${url.pathname}`;
    calls.push({ method: request.method, path: url.pathname + url.search, body });
    const handler = routes[key];
    if (!handler) return json({ detail: `no mock for ${key}` }, 404);
    const res = await handler(request, body);
    if (res === "network-error") throw new TypeError("Failed to fetch");
    return res;
  });
  vi.stubGlobal("fetch", fetchMock);
  return { calls, fetchMock };
}
