import { ImageResponse } from "next/og";

// Node runtime — plays well with `output: standalone` self-hosting.
export const runtime = "nodejs";
export const alt = "Football Predictor — market-independent ML football predictions";
export const size = { width: 1200, height: 630 };
export const contentType = "image/png";

export default function OpengraphImage() {
  return new ImageResponse(
    (
      <div
        style={{
          width: "100%",
          height: "100%",
          display: "flex",
          flexDirection: "column",
          justifyContent: "center",
          padding: "80px",
          background: "linear-gradient(135deg, #0a0f0a 0%, #0f1a14 55%, #10241a 100%)",
          color: "#f3f4f6",
          fontFamily: "sans-serif",
        }}
      >
        <div style={{ fontSize: 30, color: "#4ade80", letterSpacing: 2, marginBottom: 12 }}>
          ⚽ FOOTBALL PREDICTOR
        </div>
        <div style={{ fontSize: 68, fontWeight: 800, lineHeight: 1.05, maxWidth: 980 }}>
          Market-independent ML football predictions
        </div>
        <div style={{ fontSize: 30, color: "#9ca3af", marginTop: 24, maxWidth: 900 }}>
          1×2 · goals · BTTS · correct score · player props · live World Cup simulation
        </div>
        <div
          style={{
            display: "flex",
            gap: 16,
            marginTop: 40,
            fontSize: 24,
            color: "#d1d5db",
          }}
        >
          <span style={{ background: "#14532d", padding: "8px 18px", borderRadius: 12 }}>
            Transparent accuracy
          </span>
          <span style={{ background: "#1e3a5f", padding: "8px 18px", borderRadius: 12 }}>
            Talent-adjusted Elo
          </span>
        </div>
      </div>
    ),
    { ...size },
  );
}
