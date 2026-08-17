import { ImageResponse } from "next/og";

// Favicon-scale monogram. 32px is too small for the full "grip" wordmark, so
// this is just the lowercase g with the accent dot standing in for the "rip".
export const size = { width: 32, height: 32 };
export const contentType = "image/png";

export default function Icon() {
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
          borderRadius: "6px",
        }}
      >
        <div
          style={{
            display: "flex",
            alignItems: "baseline",
            fontSize: 22,
            fontWeight: 700,
            color: "#ededed",
            fontFamily: "sans-serif",
          }}
        >
          g
          <div
            style={{
              width: 4,
              height: 4,
              marginLeft: 1,
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
