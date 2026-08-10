"use client";

/**
 * Light / dark switch.
 *
 * Writes the cookie AND flips `data-theme` on <html> immediately, then refreshes
 * so the server re-renders with the same value. Doing only the refresh would
 * leave the page in the old theme for the length of a round trip; doing only the
 * DOM flip would snap back on the next navigation.
 */
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useT } from "@/components/LanguageProvider";
import { THEME_COOKIE, type Theme } from "@/lib/theme";

export default function ThemeToggle({ initial }: { initial: Theme }) {
  const [theme, setTheme] = useState<Theme>(initial);
  const router = useRouter();
  const t = useT();

  // Keep local state honest if the server sends a different theme (another tab
  // changed it, or the cookie expired).
  useEffect(() => setTheme(initial), [initial]);

  function toggle() {
    const next: Theme = theme === "dark" ? "light" : "dark";
    setTheme(next);
    document.documentElement.dataset.theme = next;
    // 1 year, lax: this is a display preference, not a session.
    document.cookie = `${THEME_COOKIE}=${next}; path=/; max-age=31536000; samesite=lax`;
    router.refresh();
  }

  const label = theme === "dark" ? t("theme.toLight") : t("theme.toDark");

  return (
    <button
      type="button"
      onClick={toggle}
      aria-label={label}
      title={label}
      className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg text-chalk-2
                 transition-colors hover:bg-ink-700 hover:text-chalk"
    >
      {theme === "dark" ? (
        // Offer the destination, not the current state: the control shows what
        // tapping it will give you.
        <svg className="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor"
             strokeWidth="2" strokeLinecap="round" aria-hidden>
          <circle cx="12" cy="12" r="4" />
          <path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" />
        </svg>
      ) : (
        <svg className="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor"
             strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
          <path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z" />
        </svg>
      )}
    </button>
  );
}
