"use client";
import { useState } from "react";
import { CLIENT_API_URL as API } from "@/lib/api";
import { useT, useLang } from "@/components/LanguageProvider";

export interface FeedbackItem {
  id: number;
  user_id: number | null;
  user_email: string | null;
  user_name: string | null;
  message: string;
  is_read: boolean;
  created_at: string;
}

export default function AdminFeedback({ items }: { items: FeedbackItem[] }) {
  const t = useT();
  const lang = useLang();
  const [feedback, setFeedback] = useState<FeedbackItem[]>(items);

  const markRead = async (id: number) => {
    setFeedback((f) => f.map((x) => (x.id === id ? { ...x, is_read: true } : x)));
    try {
      await fetch(`${API}/admin/feedback/${id}/read`, { method: "POST" });
    } catch {
      /* optimistic — revert not critical for an admin-only view */
    }
  };

  if (feedback.length === 0) {
    return (
      <div className="rounded-xl border border-line bg-ink-800 p-6 text-center text-sm text-chalk-3">
        {t("fb.empty")}
      </div>
    );
  }

  return (
    <div className="space-y-2">
      {feedback.map((f) => (
        <div
          key={f.id}
          className={`rounded-xl border p-4 ${
            f.is_read ? "border-line bg-ink-800" : "border-win/40 bg-win/10"
          }`}
        >
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0">
              <p className="text-sm font-medium text-chalk truncate">
                {f.user_name ?? f.user_email ?? "—"}
                {!f.is_read && (
                  <span className="ml-2 text-[10px] px-1.5 py-0.5 rounded bg-win/20 text-win font-semibold align-middle">
                    {t("fb.new")}
                  </span>
                )}
              </p>
              {f.user_email && <p className="text-xs text-chalk-3">{f.user_email}</p>}
            </div>
            <span className="text-[11px] text-chalk-3 shrink-0 tabular-nums">
              {new Date(f.created_at).toLocaleString(lang === "el" ? "el-GR" : "en-GB", {
                day: "numeric", month: "short", hour: "2-digit", minute: "2-digit",
                hour12: false, timeZone: "Europe/Athens",
              })}
            </span>
          </div>
          <p className="text-sm text-chalk mt-2 whitespace-pre-wrap break-words">{f.message}</p>
          <div className="flex items-center gap-3 mt-3">
            {f.user_email && (
              <a
                href={`mailto:${f.user_email}?subject=Re: Football Predictor`}
                className="text-xs text-chalk-2 hover:text-chalk-2"
              >
                {t("fb.reply")}
              </a>
            )}
            {!f.is_read && (
              <button
                onClick={() => markRead(f.id)}
                className="text-xs text-chalk-2 hover:text-chalk"
              >
                {t("fb.markRead")}
              </button>
            )}
          </div>
        </div>
      ))}
    </div>
  );
}
