"use client";
import { useEffect, useState } from "react";
import { Icon } from "./Icon";
import { THEME_KEY, ThemeChoice } from "@/lib/theme";

export function ThemeToggle() {
  const [theme, setTheme] = useState<ThemeChoice>("light");
  useEffect(() => { setTheme(document.documentElement.getAttribute("data-theme") === "dark" ? "dark" : "light"); }, []);
  function toggle() {
    const next: ThemeChoice = theme === "dark" ? "light" : "dark";
    setTheme(next);
    document.documentElement.setAttribute("data-theme", next);
    try { localStorage.setItem(THEME_KEY, next); } catch { /* storage unavailable: the choice applies for this page view only */ }
  }
  const label = theme === "dark" ? "Switch to light theme" : "Switch to dark theme";
  return (
    <button type="button" className="icon-btn" onClick={toggle} aria-label={label} data-tip={label} data-tip-pos="bottom" aria-pressed={theme === "dark"}>
      <Icon name={theme === "dark" ? "sun" : "moon"} />
    </button>
  );
}
