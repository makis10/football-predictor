import type { MetadataRoute } from "next";

const SITE_URL =
  process.env.NEXT_PUBLIC_SITE_URL || "https://aitipster.net";

export default function robots(): MetadataRoute.Robots {
  return {
    rules: {
      userAgent: "*",
      allow: "/",
      // Keep private / per-user / API routes out of the index.
      disallow: ["/admin", "/api/", "/profile", "/my-matches", "/my-roi", "/login"],
    },
    sitemap: `${SITE_URL}/sitemap.xml`,
  };
}
