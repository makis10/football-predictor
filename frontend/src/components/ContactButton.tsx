"use client";
import { useSession } from "next-auth/react";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { CLIENT_API_URL as API } from "@/lib/api";
import { useT } from "@/components/LanguageProvider";

export default function ContactButton() {
  const t = useT();
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
      setError(t("contact.emptyMsg"));
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
        setError(detail?.detail ?? t("contact.genericErr"));
        return;
      }
      setSent(true);
      setMessage("");
    } catch {
      setError(t("contact.sendFail"));
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
        title={t("contact.title")}
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
              <h2 className="text-sm font-semibold text-white">{t("contact.heading")}</h2>
              <button onClick={close} className="text-gray-500 hover:text-white text-lg leading-none">
                ×
              </button>
            </div>

            {sent ? (
              <div className="py-6 text-center space-y-2">
                <p className="text-3xl">✅</p>
                <p className="text-sm text-gray-200">{t("contact.thanks")}</p>
                <button
                  onClick={close}
                  className="mt-2 px-4 py-1.5 rounded-lg bg-green-600 hover:bg-green-500 text-white text-xs font-medium"
                >
                  {t("contact.close")}
                </button>
              </div>
            ) : (
              <>
                <p className="text-xs text-gray-500 mb-2 leading-relaxed">
                  {t("contact.blurb")}
                </p>
                <textarea
                  value={message}
                  onChange={(e) => setMessage(e.target.value)}
                  maxLength={2000}
                  rows={5}
                  autoFocus
                  placeholder={t("contact.placeholder")}
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
                    {t("contact.cancel")}
                  </button>
                  <button
                    onClick={submit}
                    disabled={sending}
                    className="px-4 py-1.5 rounded-lg bg-green-600 hover:bg-green-500 disabled:opacity-50 text-white text-xs font-medium"
                  >
                    {sending ? t("contact.sending") : t("contact.send")}
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
