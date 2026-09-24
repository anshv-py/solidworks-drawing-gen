import { describe, expect, it } from "vitest";
import { parseProblem } from "./api";

describe("parseProblem", () => {
  it("reads RFC 9457 problem details", async () => {
    const res = new Response(JSON.stringify({ code: "FILE_TOO_LARGE", detail: "too big" }), { status: 413 });
    const p = await parseProblem(res);
    expect([p.status, p.code, p.message]).toEqual([413, "FILE_TOO_LARGE", "too big"]);
  });
  it("falls back for non-JSON bodies", async () => {
    const p = await parseProblem(new Response("oops", { status: 502, statusText: "Bad Gateway" }));
    expect(p.code).toBe("HTTP_502");
  });
});
