export type ThemeChoice = "light" | "dark";
export const THEME_KEY = "avoenix-theme";

/** Resolve the initial theme: a stored choice wins, otherwise the OS preference. Storage may be unavailable (private mode), so every access is guarded. */
export function resolveTheme(stored: string | null | undefined, prefersDark: boolean): ThemeChoice {
  return stored === "light" || stored === "dark" ? stored : prefersDark ? "dark" : "light";
}

// Runs before first paint (inlined in app/layout.tsx) so there is no flash of the wrong theme.
export const NO_FLASH_SCRIPT = `(function(){try{var s=null;try{s=localStorage.getItem("${THEME_KEY}")}catch(e){}var d=window.matchMedia&&window.matchMedia("(prefers-color-scheme: dark)").matches;document.documentElement.setAttribute("data-theme",s==="light"||s==="dark"?s:(d?"dark":"light"))}catch(e){document.documentElement.setAttribute("data-theme","light")}})();`;
