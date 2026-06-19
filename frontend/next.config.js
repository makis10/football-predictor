/** @type {import('next').NextConfig} */
const nextConfig = {
  output: "standalone",

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
};

module.exports = nextConfig;
