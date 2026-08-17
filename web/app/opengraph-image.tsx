import { ImageResponse } from "next/og";
import { VERSION, endToEnd } from "@/lib/metrics";

export const size = { width: 1200, height: 630 };
export const contentType = "image/png";

// ImageResponse only understands flexbox and literal values, no CSS vars, no
// Tailwind, so the Geist tokens from globals.css are hardcoded here instead.
export default function OpengraphImage() {
  return new ImageResponse(
    (
      <div
        style={{
          width: "100%",
          height: "100%",
          display: "flex",
          flexDirection: "column",
          justifyContent: "space-between",
          padding: 80,
          backgroundColor: "#0a0a0a",
          color: "#ededed",
          fontFamily: "sans-serif",
        }}
      >
        <div style={{ display: "flex", alignItems: "baseline", gap: 16 }}>
          <div style={{ fontSize: 56, fontWeight: 600, letterSpacing: -2 }}>
            grip
          </div>
          <div
            style={{
              display: "flex",
              fontSize: 22,
              color: "#ffffff",
              backgroundColor: "#006bff",
              padding: "4px 12px",
              borderRadius: 999,
            }}
          >
            v{VERSION}
          </div>
        </div>

        <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
          <div
            style={{
              display: "flex",
              alignItems: "baseline",
              gap: 20,
              borderLeft: "4px solid #006bff",
              paddingLeft: 24,
            }}
          >
            <div style={{ fontSize: 84, fontWeight: 600, letterSpacing: -3 }}>
              {endToEnd.median}
            </div>
            <div
              style={{
                display: "flex",
                maxWidth: 620,
                paddingLeft: 20,
                fontSize: 28,
                lineHeight: 1.4,
                color: "#8f8f8f",
              }}
            >
              {endToEnd.what}, {endToEnd.repeatRuns} across repeat runs
            </div>
          </div>

          <div style={{ display: "flex", fontSize: 32, color: "#8f8f8f" }}>
            a browser your agent can afford to look at
          </div>
        </div>
      </div>
    ),
    { ...size },
  );
}
