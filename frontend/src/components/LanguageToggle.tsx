"use client";

/**
 * Header language switch.
 *
 * Desktop shows both flags with the active one highlighted. Below `sm` only the
 * INACTIVE flag renders: two flags cost ~60px of a 375px header row to tell the
 * reader something the page itself already tells them, and that row is exactly
 * where the site used to overflow. One flag still means "switch to this".
 */
import { useLang, useSetLang } from "@/components/LanguageProvider";
import { useT } from "@/components/LanguageProvider";

export default function LanguageToggle() {
  const lang = useLang();
  const setLang = useSetLang();
  const t = useT();

  return (
    <div className="flex items-center gap-0.5 rounded-full bg-ink-700/60 p-0.5">
      <button
        type="button"
        onClick={() => setLang("en")}
        aria-label={t("lang.english")}
        aria-pressed={lang === "en"}
        title={t("lang.english")}
        className={`h-7 w-7 rounded-full text-base leading-none flex items-center justify-center transition-all ${
          lang === "en"
            ? "bg-ink-600 ring-1 ring-chalk-2/40 hidden sm:flex"
            : "opacity-60 hover:opacity-100"
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
        className={`h-7 w-7 rounded-full text-base leading-none flex items-center justify-center transition-all ${
          lang === "el"
            ? "bg-ink-600 ring-1 ring-chalk-2/40 hidden sm:flex"
            : "opacity-60 hover:opacity-100"
        }`}
      >
        🇬🇷
      </button>
    </div>
  );
}
