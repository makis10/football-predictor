/**
 * Server-side locale access. Reads the `locale` cookie so async server
 * components render in the user's chosen language.
 *
 * `await cookies()` works across Next 14 (sync value) and 15/16 (Promise), so
 * these helpers are async and version-proof.
 *
 * NOTE: reading cookies opts the caller into dynamic rendering. That's fine
 * here — every translated page already renders per-request live data.
 */
import { cookies } from "next/headers";

import { LOCALE_COOKIE, type Lang, type TFunc, getT, normalizeLang } from "./i18n";

export async function getServerLang(): Promise<Lang> {
  const store = await cookies();
  return normalizeLang(store.get(LOCALE_COOKIE)?.value);
}

export async function getServerT(): Promise<TFunc> {
  return getT(await getServerLang());
}
