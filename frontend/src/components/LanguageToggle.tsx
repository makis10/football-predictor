"use client";

/**
 * Header language switch — two flags (English / Greek). The active language is
 * highlighted; clicking the other flag switches instantly.
 */
import { useLang, useSetLang } from "@/components/LanguageProvider";
import { useT } from "@/components/LanguageProvider";

export default function LanguageToggle() {
  const lang = useLang();
  const setLang = useSetLang();
  const t = useT();

  return (
    <div className="flex items-center gap-0.5 rounded-full bg-pitch-800/60 p-0.5">
      <button
        type="button"
        onClick={() => setLang("en")}
        aria-label={t("lang.english")}
        aria-pressed={lang === "en"}
        title={t("lang.english")}
        className={`w-7 h-7 rounded-full text-base leading-none flex items-center justify-center transition-all ${
          lang === "en" ? "bg-pitch-700 ring-1 ring-green-500/50" : "opacity-50 hover:opacity-100"
        }`}
      >
        🇬🇧
      </button>
      <button
        type="button"
        onClick={() => setLang("el")}
        aria-label={t("lang.greek")}
        aria-pressed={lang === "el"}
        title={t("lang.greek")}
        className={`w-7 h-7 rounded-full text-base leading-none flex items-center justify-center transition-all ${
          lang === "el" ? "bg-pitch-700 ring-1 ring-green-500/50" : "opacity-50 hover:opacity-100"
        }`}
      >
        🇬🇷
      </button>
    </div>
  );
}
