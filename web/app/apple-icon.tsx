import { ImageResponse } from "next/og";

// iOS home-screen icon. 180px has room for the accent bracket that the
// 32px favicon has to drop.
export const size = { width: 180, height: 180 };
export const contentType = "image/png";

export default function AppleIcon() {
  return new ImageResponse(
    (
      <div
        style={{
          width: "100%",
          height: "100%",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          background: "#0a0a0a",
        }}
      >
        <div style={{ display: "flex", alignItems: "center" }}>
          <div
            style={{
              display: "flex",
              fontSize: 96,
              fontWeight: 700,
              color: "#ededed",
              fontFamily: "sans-serif",
              lineHeight: 1,
            }}
          >
            g
          </div>
          <div
            style={{
              display: "flex",
              width: 16,
              height: 16,
              marginLeft: 6,
              marginBottom: 8,
              borderRadius: "50%",
              background: "#006bff",
            }}
          />
        </div>
      </div>
    ),
    { ...size }
  );
}
