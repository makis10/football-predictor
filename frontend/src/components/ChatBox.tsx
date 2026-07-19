"use client";

import { useState, useRef, useEffect } from "react";
import { sendChat, ChatMessage } from "@/lib/api";
import { useT } from "@/components/LanguageProvider";

// ── Icons ─────────────────────────────────────────────────────────────────────

function IconChat() {
  return (
    <svg className="w-6 h-6" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8}>
      <path strokeLinecap="round" strokeLinejoin="round"
        d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z" />
    </svg>
  );
}

function IconClose() {
  return (
    <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
    </svg>
  );
}

function IconSend() {
  return (
    <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M12 19l9 2-9-18-9 18 9-2zm0 0v-8" />
    </svg>
  );
}

// ── Typing indicator ──────────────────────────────────────────────────────────

function TypingIndicator() {
  return (
    <div className="flex items-end gap-2 justify-start">
      <span className="text-lg">🤖</span>
      <div className="bg-pitch-700 rounded-2xl rounded-bl-sm px-4 py-2.5 flex gap-1 items-center">
        {[0, 1, 2].map((i) => (
          <span
            key={i}
            className="w-1.5 h-1.5 rounded-full bg-gray-400 animate-bounce"
            style={{ animationDelay: `${i * 0.15}s` }}
          />
        ))}
      </div>
    </div>
  );
}

// ── Quick-prompt chips ────────────────────────────────────────────────────────

const QUICK_PROMPT_KEYS = [
  "chat.suggest1",
  "chat.suggest2",
  "chat.suggest3",
  "chat.suggest4",
];

// ── Main component ────────────────────────────────────────────────────────────

const STORAGE_KEY = "chat:messages";

export default function ChatBox() {
  const t = useT();
  const [open, setOpen]       = useState(false);
  const [input, setInput]     = useState("");
  const [loading, setLoading] = useState(false);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const bottomRef = useRef<HTMLDivElement>(null);
  const inputRef  = useRef<HTMLTextAreaElement>(null);

  // Restore conversation from the current tab session (survives navigation
  // between pages; cleared when the tab closes).
  useEffect(() => {
    try {
      const saved = sessionStorage.getItem(STORAGE_KEY);
      if (saved) setMessages(JSON.parse(saved));
    } catch {
      /* ignore malformed/blocked storage */
    }
  }, []);

  // Persist on every change (skip the empty initial state so we don't clobber
  // a restore that hasn't run yet).
  useEffect(() => {
    if (messages.length === 0) return;
    try {
      sessionStorage.setItem(STORAGE_KEY, JSON.stringify(messages));
    } catch {
      /* storage full / blocked — non-fatal */
    }
  }, [messages]);

  // Auto-scroll to bottom when messages change
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, loading]);

  // Focus input when panel opens
  useEffect(() => {
    if (open) setTimeout(() => inputRef.current?.focus(), 50);
  }, [open]);

  async function sendMessage(text: string) {
    const trimmed = text.trim();
    if (!trimmed || loading) return;

    const userMsg: ChatMessage = { role: "user", content: trimmed };
    const next = [...messages, userMsg];
    setMessages(next);
    setInput("");
    setLoading(true);

    try {
      // Send full history so Groq has context for follow-up questions
      const { reply } = await sendChat(trimmed, messages);
      setMessages([...next, { role: "assistant", content: reply }]);
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : t("chat.error");
      setMessages([...next, { role: "assistant", content: `⚠️ ${msg}` }]);
    } finally {
      setLoading(false);
    }
  }

  function handleKey(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendMessage(input);
    }
  }

  return (
    <>
      {/* ── Floating toggle button ── */}
      <button
        onClick={() => setOpen((v) => !v)}
        aria-label="Toggle chat assistant"
        className={`
          fixed bottom-16 right-4 z-50
          w-12 h-12 rounded-full shadow-lg
          flex items-center justify-center
          transition-all duration-200
          ${open
            ? "bg-pitch-700 text-gray-300 hover:bg-pitch-600"
            : "bg-green-600 text-white hover:bg-green-500"
          }
        `}
      >
        {open ? <IconClose /> : <IconChat />}
      </button>

      {/* ── Chat panel ── */}
      {open && (
        <div
          className="
            fixed bottom-28 right-4 z-50
            w-[340px] sm:w-[380px]
            h-[520px]
            flex flex-col
            rounded-2xl shadow-2xl
            border border-pitch-700
            bg-pitch-900
            overflow-hidden
          "
        >
          {/* Header */}
          <div className="flex items-center gap-2 px-4 py-3 border-b border-pitch-700 bg-pitch-800 shrink-0">
            <span className="text-lg">⚽</span>
            <div className="flex-1 min-w-0">
              <p className="text-sm font-semibold text-white leading-none">Prediction Assistant</p>
              <p className="text-[10px] text-gray-500 mt-0.5">Llama 3.3 70B · Groq</p>
            </div>
            <button
              onClick={() => setOpen(false)}
              className="text-gray-500 hover:text-gray-300 transition-colors p-1"
            >
              <IconClose />
            </button>
          </div>

          {/* Message list */}
          <div className="flex-1 overflow-y-auto px-3 py-3 space-y-3">
            {messages.length === 0 && !loading && (
              <div className="space-y-3">
                <p className="text-xs text-gray-500 text-center pt-2">
                  {t("chat.askMe")}
                </p>
                <div className="flex flex-col gap-1.5">
                  {QUICK_PROMPT_KEYS.map((key) => (
                    <button
                      key={key}
                      onClick={() => sendMessage(t(key))}
                      className="
                        text-left text-xs text-gray-300 px-3 py-2 rounded-xl
                        bg-pitch-800 hover:bg-pitch-700 border border-pitch-700
                        hover:border-green-700 transition-colors
                      "
                    >
                      {t(key)}
                    </button>
                  ))}
                </div>
              </div>
            )}

            {messages.map((msg, i) => (
              <div
                key={i}
                className={`flex items-end gap-2 ${
                  msg.role === "user" ? "justify-end" : "justify-start"
                }`}
              >
                {msg.role === "assistant" && <span className="text-lg shrink-0">🤖</span>}
                <div
                  className={`
                    max-w-[85%] rounded-2xl px-3.5 py-2.5 text-sm leading-relaxed whitespace-pre-wrap
                    ${msg.role === "user"
                      ? "bg-green-700 text-white rounded-br-sm"
                      : "bg-pitch-700 text-gray-200 rounded-bl-sm"
                    }
                  `}
                >
                  {msg.content}
                </div>
                {msg.role === "user" && <span className="text-lg shrink-0">👤</span>}
              </div>
            ))}

            {loading && <TypingIndicator />}
            <div ref={bottomRef} />
          </div>

          {/* Input area */}
          <div className="shrink-0 border-t border-pitch-700 bg-pitch-800 p-3">
            <div className="flex items-end gap-2">
              <textarea
                ref={inputRef}
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={handleKey}
                placeholder={t("chat.placeholder")}
                rows={1}
                className="
                  flex-1 resize-none rounded-xl bg-pitch-700 border border-pitch-600
                  text-sm text-gray-200 placeholder-gray-600
                  px-3 py-2 focus:outline-none focus:border-green-600
                  max-h-28 overflow-y-auto
                "
                style={{ lineHeight: "1.4" }}
                disabled={loading}
              />
              <button
                onClick={() => sendMessage(input)}
                disabled={loading || !input.trim()}
                className="
                  shrink-0 w-9 h-9 rounded-xl
                  bg-green-600 hover:bg-green-500 disabled:bg-pitch-700
                  text-white disabled:text-gray-600
                  flex items-center justify-center
                  transition-colors
                "
              >
                <IconSend />
              </button>
            </div>
            <p className="text-[10px] text-gray-700 mt-1.5 text-center">
              {t("chat.enterHint")}
            </p>
          </div>
        </div>
      )}
    </>
  );
}
