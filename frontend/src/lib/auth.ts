/**
 * Auth utilities for server components.
 * Use these to get the current user's ID and make authenticated API calls.
 */
import { getServerSession } from "next-auth/next";
import { authOptions } from "@/lib/auth-options";

export async function getSession() {
  return getServerSession(authOptions);
}

export async function getCurrentUserId(): Promise<string | null> {
  const session = await getSession();
  return (session?.user as any)?.id ?? null;
}

/**
 * Fetch from internal API with user auth header.
 * Use in server components / server actions.
 */
export async function fetchWithAuth(path: string, options: RequestInit = {}) {
  const userId = await getCurrentUserId();
  const baseUrl = process.env.INTERNAL_API_URL ?? "http://localhost:8000";
  const internalSecret = process.env.INTERNAL_API_SECRET;
  return fetch(`${baseUrl}${path}`, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...(userId ? { "X-User-Id": userId } : {}),
      ...(internalSecret ? { "X-Internal-Secret": internalSecret } : {}),
      ...(options.headers ?? {}),
    },
  });
}
