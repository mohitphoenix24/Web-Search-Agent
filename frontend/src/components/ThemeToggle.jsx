import { useEffect, useState } from "react";
import { MoonIcon, SunIcon } from "./Icons";

// Light / dark switch.
//
// Until you press it, the app follows your computer's setting. Once you pick
// one, the choice is saved in this browser and wins over the system setting.
//
// How it works: we put data-theme="light" or "dark" on the <html> element, and
// styles.css has a matching block of colours for each. The same value is saved
// in localStorage, and a tiny script in index.html reads it back before the
// page is drawn — otherwise you would see a white flash on every reload.

const KEY = "wsa-theme";

const systemTheme = () =>
  window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";

// localStorage can be blocked (private windows, strict settings), so never
// let it throw and break the whole app.
const readSaved = () => {
  try {
    const saved = localStorage.getItem(KEY);
    return saved === "light" || saved === "dark" ? saved : null;
  } catch {
    return null;
  }
};

export default function ThemeToggle() {
  const [theme, setTheme] = useState(() => readSaved() ?? systemTheme());
  const [chosen, setChosen] = useState(() => readSaved() !== null);

  // Tell the page which theme to use
  useEffect(() => {
    document.documentElement.dataset.theme = theme;
  }, [theme]);

  // Follow the system if the user hasn't picked one (e.g. macOS at sunset)
  useEffect(() => {
    if (chosen) return;
    const media = window.matchMedia("(prefers-color-scheme: dark)");
    const update = () => setTheme(systemTheme());
    media.addEventListener("change", update);
    return () => media.removeEventListener("change", update);
  }, [chosen]);

  function toggle() {
    const next = theme === "dark" ? "light" : "dark";
    setTheme(next);
    setChosen(true);
    try {
      localStorage.setItem(KEY, next);
    } catch {
      /* not important — the theme still works for this visit */
    }
  }

  const goingDark = theme === "light";
  return (
    <button
      className="icon-btn theme-btn"
      onClick={toggle}
      title={`Switch to ${goingDark ? "dark" : "light"} mode`}
      aria-label={`Switch to ${goingDark ? "dark" : "light"} mode`}
    >
      {goingDark ? <MoonIcon size={17} /> : <SunIcon size={17} />}
    </button>
  );
}
