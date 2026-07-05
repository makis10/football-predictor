import { withAuth } from "next-auth/middleware";

export default withAuth({
  pages: {
    signIn: "/login",
  },
});

// Protect ONLY the personal / admin areas. Everything else — predictions, stats,
// recent results, the World Cup pages, robots/sitemap/OG — is PUBLIC, so visitors
// (and search-engine crawlers) can see the product without a login wall. That's
// essential for the showcase/reach goal; personal data stays gated.
export const config = {
  matcher: [
    "/admin/:path*",
    "/profile/:path*",
    "/my-matches/:path*",
    "/my-roi/:path*",
    "/settings/:path*",
  ],
};
