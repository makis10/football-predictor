/** @type {import('next').NextConfig} */
const nextConfig = {
  output: "standalone",

  // Next 15.2+/16: the dev server rejects cross-origin requests from non-local
  // hosts unless allow-listed. We serve through ngrok, so allow that origin.
  // Override via ALLOWED_DEV_ORIGINS (comma-separated) when the ngrok URL rotates.
  allowedDevOrigins: process.env.ALLOWED_DEV_ORIGINS
    ? process.env.ALLOWED_DEV_ORIGINS.split(",").map((s) => s.trim())
    : ["hamster-manger-uplifting.ngrok-free.dev"],

  // NOTE: /api/proxy/* is handled by the code route at
  // src/app/api/proxy/[...path]/route.ts — NOT a rewrite. A rewrite would pass
  // the browser's headers straight through, letting a logged-in user spoof
  // X-User-Id. The route handler derives identity from the verified JWT instead.
  images: {
    remotePatterns: [
      { protocol: "https", hostname: "lh3.googleusercontent.com" },   // Google avatars
      { protocol: "https", hostname: "avatars.githubusercontent.com" }, // GitHub avatars
    ],
  },
  experimental: {
    // 0 = no client-side Router Cache for force-dynamic pages.
    // Every navigation triggers fresh SSR — required for live odds/scores/predictions.
    staleTimes: { dynamic: 0 },
  },

  // Self-hosted umami analytics, proxied same-origin so visitors' browsers only
  // ever talk to our public URL (no extra tunnel/port, adblock-resistant).
  // Safe as a rewrite: pure telemetry, no auth headers involved (unlike
  // /api/proxy, which must stay a code route — see note above).
  async rewrites() {
    return [
      { source: "/u/script.js", destination: "http://umami:3000/script.js" },
      { source: "/u/api/send", destination: "http://umami:3000/api/send" },
    ];
  },
};

module.exports = nextConfig;
