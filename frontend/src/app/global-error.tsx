"use client";

/**
 * Last-resort boundary: an error thrown by the ROOT layout itself.
 *
 * At this point the layout never rendered, so there is no provider, no theme
 * cookie applied, no fonts and no globals.css — this file must ship its own
 * <html> and <body> and style itself inline. It also cannot translate: `useT`
 * lives inside the provider that just failed to mount.
 *
 * It should almost never be seen. It exists so that when it is, the reader gets
 * a readable page and a way back instead of a white screen.
 */
export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <html lang="en">
      <body
        style={{
          margin: 0,
          minHeight: "100vh",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          background: "#080b14",
          color: "#f2f5fa",
          fontFamily: "system-ui, sans-serif",
          textAlign: "center",
          padding: "2rem",
        }}
      >
        <div>
          <p style={{ fontSize: "2rem", margin: 0 }}>⚠️</p>
          <h1 style={{ fontSize: "1.25rem", margin: "1rem 0 0.5rem" }}>
            Football Predictor is having a problem
          </h1>
          <p style={{ color: "#9aa4ba", fontSize: "0.875rem", margin: 0 }}>
            Something failed before the page could load. Reloading usually fixes it.
          </p>
          <button
            type="button"
            onClick={reset}
            style={{
              marginTop: "1.5rem",
              padding: "0.5rem 1rem",
              borderRadius: "0.5rem",
              border: 0,
              background: "#f2f5fa",
              color: "#080b14",
              fontWeight: 600,
              cursor: "pointer",
            }}
          >
            Try again
          </button>
          {error.digest && (
            <p style={{ marginTop: "1.5rem", color: "#5e6880", fontSize: "0.7rem" }}>
              Reference: {error.digest}
            </p>
          )}
        </div>
      </body>
    </html>
  );
}
