"use client";
import { signOut, useSession } from "next-auth/react";
import Link from "next/link";
import Image from "next/image";
import { useState } from "react";

export default function UserNav() {
  const { data: session, status } = useSession();
  const [open, setOpen] = useState(false);

  if (status === "loading") {
    return <div className="w-8 h-8 rounded-full bg-pitch-700 animate-pulse" />;
  }

  if (!session) {
    return (
      <Link
        href="/login"
        className="px-3 py-1.5 rounded-lg text-sm text-gray-400 hover:text-white hover:bg-pitch-800 transition-colors"
      >
        Sign in
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
        className="flex items-center gap-2 rounded-full hover:ring-2 hover:ring-green-500 transition-all"
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
          <div className="w-8 h-8 rounded-full bg-green-700 flex items-center justify-center text-xs font-bold text-white">
            {initials}
          </div>
        )}
      </button>

      {open && (
        <>
          {/* Backdrop */}
          <div className="fixed inset-0 z-40" onClick={() => setOpen(false)} />
          {/* Dropdown */}
          <div className="absolute right-0 top-10 z-50 w-52 rounded-xl border border-pitch-700 bg-pitch-900 shadow-xl py-1">
            <div className="px-4 py-2 border-b border-pitch-700">
              <p className="text-sm font-medium text-white truncate">{user?.name ?? "User"}</p>
              <p className="text-xs text-gray-500 truncate">{user?.email}</p>
            </div>

            {isAdmin && (
              <Link
                href="/admin"
                onClick={() => setOpen(false)}
                className="flex items-center gap-2 px-4 py-2 text-sm text-amber-400 hover:text-amber-300 hover:bg-pitch-800 transition-colors"
              >
                ⚙️ Admin Panel
              </Link>
            )}

            <Link
              href="/my-matches"
              onClick={() => setOpen(false)}
              className="flex items-center gap-2 px-4 py-2 text-sm text-gray-300 hover:text-white hover:bg-pitch-800 transition-colors"
            >
              🔖 My Matches
            </Link>
            <Link
              href="/my-roi"
              onClick={() => setOpen(false)}
              className="flex items-center gap-2 px-4 py-2 text-sm text-gray-300 hover:text-white hover:bg-pitch-800 transition-colors"
            >
              📊 My ROI
            </Link>
            <Link
              href="/profile"
              onClick={() => setOpen(false)}
              className="flex items-center gap-2 px-4 py-2 text-sm text-gray-300 hover:text-white hover:bg-pitch-800 transition-colors"
            >
              👤 Profile
            </Link>

            <div className="border-t border-pitch-700 mt-1">
              <button
                onClick={() => signOut({ callbackUrl: "/" })}
                className="w-full text-left flex items-center gap-2 px-4 py-2 text-sm text-red-400 hover:text-red-300 hover:bg-pitch-800 transition-colors"
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
