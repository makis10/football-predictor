import { withAuth } from "next-auth/middleware";

export default withAuth({
  pages: {
    signIn: "/login",
  },
});

// Apply to every route EXCEPT login, register, NextAuth, proxy API routes, and static assets
export const config = {
  matcher: [
    "/((?!login|register|api/auth|api/proxy|_next/static|_next/image|favicon.ico).*)",
  ],
};
