"use client";
import { useState } from "react";

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

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
      <div className="rounded-xl border border-pitch-700 bg-pitch-900 p-6 text-center text-sm text-gray-500">
        Κανένα μήνυμα ακόμα.
      </div>
    );
  }

  return (
    <div className="space-y-2">
      {feedback.map((f) => (
        <div
          key={f.id}
          className={`rounded-xl border p-4 ${
            f.is_read ? "border-pitch-700 bg-pitch-900" : "border-green-700/50 bg-green-900/10"
          }`}
        >
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0">
              <p className="text-sm font-medium text-white truncate">
                {f.user_name ?? f.user_email ?? "—"}
                {!f.is_read && (
                  <span className="ml-2 text-[10px] px-1.5 py-0.5 rounded bg-green-500/20 text-green-400 font-semibold align-middle">
                    ΝΕΟ
                  </span>
                )}
              </p>
              {f.user_email && <p className="text-xs text-gray-500">{f.user_email}</p>}
            </div>
            <span className="text-[11px] text-gray-600 shrink-0 tabular-nums">
              {new Date(f.created_at).toLocaleString("el-GR", {
                day: "numeric", month: "short", hour: "2-digit", minute: "2-digit",
                timeZone: "Europe/Athens",
              })}
            </span>
          </div>
          <p className="text-sm text-gray-200 mt-2 whitespace-pre-wrap break-words">{f.message}</p>
          <div className="flex items-center gap-3 mt-3">
            {f.user_email && (
              <a
                href={`mailto:${f.user_email}?subject=Re: Football Predictor`}
                className="text-xs text-sky-400 hover:text-sky-300"
              >
                Απάντηση ↗
              </a>
            )}
            {!f.is_read && (
              <button
                onClick={() => markRead(f.id)}
                className="text-xs text-gray-400 hover:text-white"
              >
                Σήμανση ως διαβασμένο
              </button>
            )}
          </div>
        </div>
      ))}
    </div>
  );
}
