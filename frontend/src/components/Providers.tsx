"use client";
import { SessionProvider } from "next-auth/react";

import { LanguageProvider } from "@/components/LanguageProvider";
import type { Lang } from "@/lib/i18n";

export default function Providers({
  initialLang,
  children,
}: {
  initialLang: Lang;
  children: React.ReactNode;
}) {
  return (
    <SessionProvider>
      <LanguageProvider initialLang={initialLang}>{children}</LanguageProvider>
    </SessionProvider>
  );
}
