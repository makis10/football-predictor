/**
 * Theme selection, stored the same way as the language: a first-party cookie
 * read on the server and stamped onto <html data-theme>.
 *
 * Why a cookie and not localStorage: the server has to know the theme at render
 * time. Reading it on the client instead would paint the dark page first and
 * repaint light on hydration — the flash every "add a light mode" tutorial
 * ships and nobody removes.
 */
export type Theme = "dark" | "light";

export const THEME_COOKIE = "theme";
export const DEFAULT_THEME: Theme = "dark";

export function normalizeTheme(v: string | undefined | null): Theme {
  return v === "light" ? "light" : "dark";
}
