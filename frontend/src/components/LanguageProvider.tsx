"use client";

/**
 * Client-side language context. Seeded from the server-read cookie via
 * `initialLang` so the first client render matches SSR (no hydration flash).
 *
 * Switching language writes the cookie, updates context (instant re-render of
 * client components) and calls router.refresh() (re-renders server components
 * with the new cookie).
 */
import { createContext, useCallback, useContext, useState } from "react";
import { useRouter } from "next/navigation";

import { DEFAULT_LANG, LOCALE_COOKIE, type Lang, type TFunc, getT } from "@/lib/i18n";

interface LangCtx {
  lang: Lang;
  setLang: (l: Lang) => void;
  t: TFunc;
}

const Ctx = createContext<LangCtx>({
  lang: DEFAULT_LANG,
  setLang: () => {},
  t: getT(DEFAULT_LANG),
});

export function LanguageProvider({
  initialLang,
  children,
}: {
  initialLang: Lang;
  children: React.ReactNode;
}) {
  const [lang, setLangState] = useState<Lang>(initialLang);
  const router = useRouter();

  const setLang = useCallback(
    (l: Lang) => {
      // 1-year cookie, first-party, root path.
      document.cookie = `${LOCALE_COOKIE}=${l}; path=/; max-age=31536000; SameSite=Lax`;
      setLangState(l);
      router.refresh();
    },
    [router],
  );

  return (
    <Ctx.Provider value={{ lang, setLang, t: getT(lang) }}>
      {children}
    </Ctx.Provider>
  );
}

export function useLang(): Lang {
  return useContext(Ctx).lang;
}

export function useSetLang(): (l: Lang) => void {
  return useContext(Ctx).setLang;
}

export function useT(): TFunc {
  return useContext(Ctx).t;
}
