import type { NextAuthOptions } from "next-auth";
import GoogleProvider from "next-auth/providers/google";
import CredentialsProvider from "next-auth/providers/credentials";

const INTERNAL_API = process.env.INTERNAL_API_URL ?? "http://localhost:8000";

// How often the JWT re-checks is_admin against the backend (ms).
const ADMIN_REFRESH_MS = 5 * 60 * 1000;

// Shared secret proving these server-side calls come from the trusted Next.js
// server (the backend enforces it on /auth/*). No-op header when unset (dev).
function internalHeaders(): Record<string, string> {
  const h: Record<string, string> = { "Content-Type": "application/json" };
  if (process.env.INTERNAL_API_SECRET) h["X-Internal-Secret"] = process.env.INTERNAL_API_SECRET;
  return h;
}

export const authOptions: NextAuthOptions = {
  secret: process.env.NEXTAUTH_SECRET,

  providers: [
    // ── Google OAuth ─────────────────────────────────────────────────────────
    ...(process.env.GOOGLE_CLIENT_ID && process.env.GOOGLE_CLIENT_SECRET
      ? [
          GoogleProvider({
            clientId:     process.env.GOOGLE_CLIENT_ID,
            clientSecret: process.env.GOOGLE_CLIENT_SECRET,
          }),
        ]
      : []),

    // ── Email + Password ─────────────────────────────────────────────────────
    CredentialsProvider({
      name: "credentials",
      credentials: {
        email:    { label: "Email",    type: "email" },
        password: { label: "Password", type: "password" },
      },
      async authorize(credentials) {
        if (!credentials?.email || !credentials?.password) return null;
        try {
          const res = await fetch(`${INTERNAL_API}/auth/login`, {
            method:  "POST",
            headers: internalHeaders(),
            body:    JSON.stringify({
              email:    credentials.email,
              password: credentials.password,
            }),
          });
          if (!res.ok) return null;
          const user = await res.json();
          return { id: String(user.id), email: user.email, name: user.name, image: user.image, isAdmin: user.is_admin ?? false };
        } catch {
          return null;
        }
      },
    }),
  ],

  callbacks: {
    async signIn({ user, account }) {
      if (account?.provider === "google") {
        try {
          const res = await fetch(`${INTERNAL_API}/auth/oauth`, {
            method:  "POST",
            headers: internalHeaders(),
            body:    JSON.stringify({
              email:       user.email,
              name:        user.name,
              image:       user.image,
              provider:    "google",
              provider_id: account.providerAccountId,
            }),
          });
          if (!res.ok) return false;
          const dbUser = await res.json();
          user.dbId    = String(dbUser.id);
          user.isAdmin = dbUser.is_admin ?? false;
        } catch {
          return false;
        }
      }
      return true;
    },

    async jwt({ token, user, trigger }) {
      // Initial sign-in: seed identity + admin flag from the auth response.
      if (user) {
        token.userId         = user.dbId ?? user.id;
        token.isAdmin        = user.isAdmin ?? false;
        token.adminCheckedAt = Date.now();
        return token;
      }
      // Subsequent calls: refresh is_admin from the backend at most every
      // ADMIN_REFRESH_MS (or immediately on an explicit session update) so a
      // promote/demote takes effect without forcing the user to re-login.
      const stale = Date.now() - (token.adminCheckedAt ?? 0) > ADMIN_REFRESH_MS;
      if (token.userId && (trigger === "update" || stale)) {
        try {
          const res = await fetch(`${INTERNAL_API}/users/me`, {
            headers: { ...internalHeaders(), "X-User-Id": String(token.userId) },
          });
          if (res.ok) {
            const me = await res.json();
            token.isAdmin = me.is_admin ?? false;
          }
        } catch {
          // Keep the previous flag on transient backend errors.
        }
        token.adminCheckedAt = Date.now();
      }
      return token;
    },

    async session({ session, token }) {
      if (token.userId) {
        session.user.id      = token.userId;
        session.user.isAdmin = token.isAdmin ?? false;
      }
      return session;
    },
  },

  pages: {
    signIn: "/login",
    error:  "/login",
  },

  session: { strategy: "jwt" },
};
