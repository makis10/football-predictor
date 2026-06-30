"use client";

/**
 * Header notification bell — surfaces the platform changelog.
 *
 * Unread state is per-browser (localStorage): we store the id of the newest
 * entry the user has seen. Entries newer than that count as unread and light
 * up a badge. Opening the panel marks everything read. No backend needed.
 */
import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { CHANGELOG, type ChangeTag } from "@/lib/changelog";

const STORAGE_KEY = "fp_changelog_last_read_id";

const TAG_STYLE: Record<ChangeTag, string> = {
  new:         "bg-green-900/40 text-green-300 border-green-700/40",
  improvement: "bg-sky-900/40 text-sky-300 border-sky-700/40",
  fix:         "bg-amber-900/40 text-amber-300 border-amber-700/40",
};

const TAG_LABEL: Record<ChangeTag, string> = {
  new: "New", improvement: "Improved", fix: "Fixed",
};

function fmtDate(iso: string): string {
  const d = new Date(iso + "T00:00:00");
  return d.toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" });
}

export default function NotificationBell() {
  const [open, setOpen] = useState(false);
  const [unread, setUnread] = useState(0);
  const [mounted, setMounted] = useState(false);

  // Compute unread after mount (localStorage isn't available during SSR).
  useEffect(() => {
    setMounted(true);
    const lastReadId = (() => {
      try { return localStorage.getItem(STORAGE_KEY); } catch { return null; }
    })();
    if (!lastReadId) {
      setUnread(CHANGELOG.length);
      return;
    }
    const idx = CHANGELOG.findIndex((e) => e.id === lastReadId);
    // CHANGELOG is newest-first → everything before the last-read id is unread.
    setUnread(idx === -1 ? CHANGELOG.length : idx);
  }, []);

  function toggle() {
    const next = !open;
    setOpen(next);
    if (next && CHANGELOG.length) {
      try { localStorage.setItem(STORAGE_KEY, CHANGELOG[0].id); } catch { /* ignore */ }
      setUnread(0);
    }
  }

  return (
    <div className="relative">
      <button
        onClick={toggle}
        aria-label="Platform updates"
        className="relative flex items-center justify-center w-9 h-9 rounded-full text-gray-400 hover:text-white hover:bg-pitch-800 transition-colors"
      >
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor"
          strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9" />
          <path d="M13.73 21a2 2 0 0 1-3.46 0" />
        </svg>
        {unread > 0 && (
          <span className="absolute -top-0.5 -right-0.5 min-w-[18px] h-[18px] px-1 rounded-full bg-green-600 text-white text-[10px] font-bold flex items-center justify-center">
            {unread > 9 ? "9+" : unread}
          </span>
        )}
      </button>

      {open && mounted && createPortal(
        // Portal to <body> so the overlay escapes the header's backdrop-blur
        // containing block (a backdrop-filter ancestor traps position:fixed,
        // which otherwise pins this to the 56px header instead of the viewport).
        <div
          className="z-[100] flex items-center justify-center p-4"
          style={{ position: "fixed", top: 0, right: 0, bottom: 0, left: 0 }}
        >
          {/* Backdrop */}
          <div className="absolute inset-0 bg-black/60 backdrop-blur-sm" onClick={() => setOpen(false)} />
          {/* Centered modal — wide, height-capped, internal scroll.
              Critical layout (height cap + flex) is set inline so it can't be
              dropped by a Tailwind arbitrary-value / purge quirk in the build. */}
          <div
            className="relative z-10 w-full max-w-2xl rounded-2xl border border-pitch-700 bg-pitch-900 shadow-2xl"
            style={{ display: "flex", flexDirection: "column", maxHeight: "85vh" }}
          >
            <div className="flex items-start justify-between gap-3 px-5 py-4 border-b border-pitch-700" style={{ flexShrink: 0 }}>
              <div>
                <p className="text-base font-semibold text-white">🔔 Platform updates</p>
                <p className="text-xs text-gray-500">Fixes &amp; improvements to the predictor</p>
              </div>
              <button
                onClick={() => setOpen(false)}
                aria-label="Close"
                className="shrink-0 w-8 h-8 flex items-center justify-center rounded-lg text-gray-400 hover:text-white hover:bg-pitch-800 transition-colors"
              >
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor"
                  strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M18 6 6 18" /><path d="m6 6 12 12" />
                </svg>
              </button>
            </div>
            <ul
              className="divide-y divide-pitch-800"
              style={{ flex: "1 1 auto", minHeight: 0, overflowY: "auto" }}
            >
              {CHANGELOG.map((e) => (
                <li key={e.id} className="px-5 py-3">
                  <div className="flex items-center gap-2 mb-1">
                    <span className={`text-[10px] uppercase tracking-wide font-semibold px-1.5 py-0.5 rounded border ${TAG_STYLE[e.tag]}`}>
                      {TAG_LABEL[e.tag]}
                    </span>
                    <span className="text-[11px] text-gray-500">{fmtDate(e.date)}</span>
                  </div>
                  <p className="text-sm font-medium text-gray-100">{e.title}</p>
                  <p className="text-xs text-gray-400 mt-0.5 leading-relaxed">{e.body}</p>
                </li>
              ))}
            </ul>
          </div>
        </div>,
        document.body,
      )}
    </div>
  );
}
