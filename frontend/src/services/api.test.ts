import { describe, expect, it } from "vitest";

import { toApiError } from "./api";

describe("toApiError", () => {
  it("uses the backend error envelope", async () => {
    const response = new Response(
      JSON.stringify({ error: { code: "not_found", message: "artist x not found", details: {}, request_id: "r1" } }),
      { status: 404, headers: { "Content-Type": "application/json" } },
    );
    const error = await toApiError(response);
    expect(error.status).toBe(404);
    expect(error.code).toBe("not_found");
    expect(error.message).toBe("artist x not found");
    expect(error.requestId).toBe("r1");
  });

  it("falls back for non-JSON responses", async () => {
    const response = new Response("<html>Bad Gateway</html>", { status: 502, headers: { "X-Request-ID": "r2" } });
    const error = await toApiError(response);
    expect(error.code).toBe("http_error");
    expect(error.requestId).toBe("r2");
  });
});
