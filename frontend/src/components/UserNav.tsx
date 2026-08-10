"use client";
import { signOut, useSession } from "next-auth/react";
import Link from "next/link";
import Image from "next/image";
import { useState } from "react";

export default function UserNav() {
  const { data: session, status } = useSession();
  const [open, setOpen] = useState(false);

  if (status === "loading") {
    return <div className="h-8 w-8 rounded-full bg-ink-700 animate-pulse" />;
  }

  if (!session) {
    return (
      <Link
        href="/login"
        aria-label="Sign in"
        title="Sign in"
        className="flex h-8 items-center justify-center rounded-lg px-2 text-sm text-chalk-2
                   transition-colors hover:bg-ink-700 hover:text-chalk sm:px-3"
      >
        {/* Text costs 53px in a header row that has 343px to spend at 375px wide.
            The glyph carries the same meaning below `sm`. */}
        <span className="hidden sm:inline">Sign in</span>
        <svg className="h-4 w-4 sm:hidden" viewBox="0 0 24 24" fill="none"
             stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden>
          <path d="M15 3h4a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2h-4" />
          <path d="M10 17l5-5-5-5M15 12H3" />
        </svg>
      </Link>
    );
  }

  const user    = session.user;
  const isAdmin = user?.isAdmin === true;
  const initials = user?.name
    ? user.name.split(" ").map((n) => n[0]).join("").toUpperCase().slice(0, 2)
    : user?.email?.[0]?.toUpperCase() ?? "?";

  return (
    <div className="relative">
      <button
        onClick={() => setOpen((o) => !o)}
        className="flex items-center gap-2 rounded-full hover:ring-2 hover:ring-win transition-all"
      >
        {user?.image ? (
          <Image
            src={user.image}
            alt={user.name ?? "User"}
            width={32}
            height={32}
            className="rounded-full"
          />
        ) : (
          <div className="w-8 h-8 rounded-full bg-win/15 flex items-center justify-center text-xs font-bold text-chalk">
            {initials}
          </div>
        )}
      </button>

      {open && (
        <>
          {/* Backdrop */}
          <div className="fixed inset-0 z-40" onClick={() => setOpen(false)} />
          {/* Dropdown */}
          <div className="absolute right-0 top-10 z-50 w-52 rounded-xl border border-line bg-ink-800 shadow-xl py-1">
            <div className="px-4 py-2 border-b border-line">
              <p className="text-sm font-medium text-chalk truncate">{user?.name ?? "User"}</p>
              <p className="text-xs text-chalk-3 truncate">{user?.email}</p>
            </div>

            {isAdmin && (
              <Link
                href="/admin"
                onClick={() => setOpen(false)}
                className="flex items-center gap-2 px-4 py-2 text-sm text-est hover:text-est hover:bg-ink-700 transition-colors"
              >
                ⚙️ Admin Panel
              </Link>
            )}

            <Link
              href="/my-matches"
              onClick={() => setOpen(false)}
              className="flex items-center gap-2 px-4 py-2 text-sm text-chalk-2 hover:text-chalk hover:bg-ink-700 transition-colors"
            >
              🔖 My Matches
            </Link>
            <Link
              href="/my-roi"
              onClick={() => setOpen(false)}
              className="flex items-center gap-2 px-4 py-2 text-sm text-chalk-2 hover:text-chalk hover:bg-ink-700 transition-colors"
            >
              📊 My ROI
            </Link>
            <Link
              href="/profile"
              onClick={() => setOpen(false)}
              className="flex items-center gap-2 px-4 py-2 text-sm text-chalk-2 hover:text-chalk hover:bg-ink-700 transition-colors"
            >
              👤 Profile
            </Link>

            <div className="border-t border-line mt-1">
              <button
                onClick={() => signOut({ callbackUrl: "/" })}
                className="w-full text-left flex items-center gap-2 px-4 py-2 text-sm text-lose hover:text-lose hover:bg-ink-700 transition-colors"
              >
                Sign out
              </button>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
