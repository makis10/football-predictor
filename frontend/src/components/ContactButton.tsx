"use client";
import { useSession } from "next-auth/react";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { CLIENT_API_URL as API } from "@/lib/api";

export default function ContactButton() {
  const { status } = useSession();
  const router = useRouter();
  const [mounted, setMounted] = useState(false);
  const [open, setOpen] = useState(false);

  // The modal is portalled to <body> so its `fixed` positioning is relative to
  // the viewport — the footer's backdrop-filter would otherwise make it the
  // containing block and clip the modal to the footer bar.
  useEffect(() => setMounted(true), []);
  const [message, setMessage] = useState("");
  const [sending, setSending] = useState(false);
  const [sent, setSent] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Logged-in users only (per requirement). Hidden while session resolves.
  if (status === "loading" || status === "unauthenticated") return null;

  const submit = async () => {
    const msg = message.trim();
    if (!msg) {
      setError("Γράψε ένα μήνυμα πρώτα.");
      return;
    }
    setSending(true);
    setError(null);
    try {
      const res = await fetch(`${API}/users/contact`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: msg }),
      });
      if (!res.ok) {
        const detail = await res.json().catch(() => null);
        setError(detail?.detail ?? "Κάτι πήγε στραβά. Δοκίμασε ξανά.");
        return;
      }
      setSent(true);
      setMessage("");
    } catch {
      setError("Αποτυχία αποστολής. Έλεγξε τη σύνδεσή σου.");
    } finally {
      setSending(false);
    }
  };

  const close = () => {
    setOpen(false);
    setError(null);
    // reset the success state after the modal closes so re-opening is fresh
    setTimeout(() => setSent(false), 200);
  };

  return (
    <>
      <button
        onClick={() => {
          if (status !== "authenticated") {
            router.push("/login");
            return;
          }
          setOpen(true);
        }}
        className="shrink-0 inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-pitch-700 hover:bg-pitch-600 text-gray-200 text-xs font-medium transition-colors"
        title="Στείλε μου ιδέες / προτάσεις"
      >
        ✉️ Contact
      </button>

      {open && mounted && createPortal(
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm p-4"
          onClick={close}
        >
          <div
            className="w-full max-w-md rounded-xl border border-pitch-700 bg-pitch-900 p-5 shadow-xl"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center justify-between mb-3">
              <h2 className="text-sm font-semibold text-white">✉️ Επικοινωνία</h2>
              <button onClick={close} className="text-gray-500 hover:text-white text-lg leading-none">
                ×
              </button>
            </div>

            {sent ? (
              <div className="py-6 text-center space-y-2">
                <p className="text-3xl">✅</p>
                <p className="text-sm text-gray-200">Ευχαριστώ! Το μήνυμά σου στάλθηκε.</p>
                <button
                  onClick={close}
                  className="mt-2 px-4 py-1.5 rounded-lg bg-green-600 hover:bg-green-500 text-white text-xs font-medium"
                >
                  Κλείσιμο
                </button>
              </div>
            ) : (
              <>
                <p className="text-xs text-gray-500 mb-2 leading-relaxed">
                  Στείλε μου τις ιδέες ή προτάσεις σου για το Football Predictor. Τις διαβάζω όλες.
                </p>
                <textarea
                  value={message}
                  onChange={(e) => setMessage(e.target.value)}
                  maxLength={2000}
                  rows={5}
                  autoFocus
                  placeholder="Η ιδέα / πρότασή σου…"
                  className="w-full rounded-lg bg-pitch-800 border border-pitch-700 px-3 py-2 text-sm text-gray-100 placeholder-gray-600 focus:outline-none focus:border-green-600 resize-none"
                />
                <div className="flex items-center justify-between mt-1">
                  <span className="text-[10px] text-gray-600">{message.length}/2000</span>
                  {error && <span className="text-xs text-red-400">{error}</span>}
                </div>
                <div className="flex justify-end gap-2 mt-3">
                  <button
                    onClick={close}
                    className="px-3 py-1.5 rounded-lg bg-pitch-700 hover:bg-pitch-600 text-gray-300 text-xs"
                  >
                    Άκυρο
                  </button>
                  <button
                    onClick={submit}
                    disabled={sending}
                    className="px-4 py-1.5 rounded-lg bg-green-600 hover:bg-green-500 disabled:opacity-50 text-white text-xs font-medium"
                  >
                    {sending ? "Αποστολή…" : "Αποστολή"}
                  </button>
                </div>
              </>
            )}
          </div>
        </div>,
        document.body,
      )}
    </>
  );
}
