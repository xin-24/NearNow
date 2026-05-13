import { useState, useEffect, useCallback } from "react";

export function useTheme() {
  const [dark, setDark] = useState(() => {
    const saved = localStorage.getItem("nearnow-theme");
    if (saved) return saved === "dark";
    const hour = new Date().getHours();
    return hour < 6 || hour >= 18;
  });

  useEffect(() => {
    document.body.classList.toggle("dark", dark);
  }, [dark]);

  const toggle = useCallback(() => {
    setDark((prev) => {
      const next = !prev;
      localStorage.setItem("nearnow-theme", next ? "dark" : "light");
      return next;
    });
  }, []);

  return { dark, toggle };
}
