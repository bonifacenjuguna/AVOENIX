// One consistent icon set: 24x24 grid, 1.75 stroke, round caps. Decorative by default (aria-hidden); the surrounding control carries the label.
const P: Record<string, string> = {
  plus: "M12 5v14M5 12h14", search: "M11 19a8 8 0 1 0 0-16 8 8 0 0 0 0 16zM21 21l-4.3-4.3", trash: "M4 7h16M10 11v6M14 11v6M6 7l1 12a2 2 0 0 0 2 2h6a2 2 0 0 0 2-2l1-12M9 7V4h6v3",
  copy: "M9 9h10v10H9zM5 15V5h10", check: "M5 12.5l4.5 4.5L19 7.5", download: "M12 4v11m0 0l-4-4m4 4l4-4M5 20h14", send: "M5 12l14-7-5 14-2.5-5.5L5 12z",
  sun: "M12 16a4 4 0 1 0 0-8 4 4 0 0 0 0 8zM12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4",
  moon: "M20 14.5A8 8 0 1 1 9.5 4a6.5 6.5 0 0 0 10.5 10.5z", menu: "M4 6h16M4 12h16M4 18h16", x: "M6 6l12 12M18 6L6 18", chat: "M4 5h16v11H9l-5 4V5z",
  pulse: "M3 12h4l3-8 4 16 3-8h4", db: "M4 6c0-1.7 3.6-3 8-3s8 1.3 8 3-3.6 3-8 3-8-1.3-8-3zM4 6v12c0 1.7 3.6 3 8 3s8-1.3 8-3V6M4 12c0 1.7 3.6 3 8 3s8-1.3 8-3",
  book: "M5 4h10a4 4 0 0 1 4 4v12H9a4 4 0 0 1-4-4V4zM5 16a4 4 0 0 1 4-4h10", gauge: "M4 18a8 8 0 1 1 16 0M12 18l4-6", brain: "M9 4a3 3 0 0 0-3 3 3 3 0 0 0-2 5 3 3 0 0 0 2 5 3 3 0 0 0 6 1V4a3 3 0 0 0-3 0zM15 4a3 3 0 0 1 3 3 3 3 0 0 1 2 5 3 3 0 0 1-2 5 3 3 0 0 1-3 2",
  logout: "M10 4H5v16h5M15 8l4 4-4 4M19 12H9", alert: "M12 4l9 16H3L12 4zM12 10v4M12 17.5v.01", chevron: "M9 6l6 6-6 6", file: "M6 3h8l4 4v14H6V3zM14 3v4h4", info: "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18zM12 11v5M12 8v.01",
};
export type IconName = keyof typeof P;
export function Icon({ name, size = 18 }: { name: IconName; size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.75} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" focusable="false">
      <path d={P[name]} />
    </svg>
  );
}
