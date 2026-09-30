"use client";

import React, { createContext, useContext, useEffect, useState } from "react";

export type ArchitecturalTheme = "dark" | "ivory";

interface ThemeContextType {
  theme: ArchitecturalTheme;
  toggleTheme: () => void;
  setTheme: (theme: ArchitecturalTheme) => void;
}

function applyThemeDOM(nextTheme: ArchitecturalTheme) {
  if (typeof document !== "undefined") {
    if (nextTheme === "ivory") {
      document.documentElement.setAttribute("data-theme", "architectural-ivory");
      document.documentElement.classList.remove("dark");
      document.documentElement.classList.add("theme-ivory");
    } else {
      document.documentElement.removeAttribute("data-theme");
      document.documentElement.classList.add("dark");
      document.documentElement.classList.remove("theme-ivory");
    }
  }
}

const ThemeContext = createContext<ThemeContextType>({
  theme: "dark",
  toggleTheme: () => {},
  setTheme: () => {},
});

export function ThemeProvider({ children }: { children: React.ReactNode }) {
  const [theme, setThemeState] = useState<ArchitecturalTheme>("dark");

  useEffect(() => {
    try {
      const stored = localStorage.getItem("chainsentinel_theme");
      if (stored === "ivory" || stored === "dark") {
        setThemeState(stored);
        applyThemeDOM(stored);
      }
    } catch {
      // Fallback cleanly if localStorage is restricted
    }
  }, []);

  const setTheme = (nextTheme: ArchitecturalTheme) => {
    setThemeState(nextTheme);
    applyThemeDOM(nextTheme);
    try {
      localStorage.setItem("chainsentinel_theme", nextTheme);
    } catch {
      // safe
    }
  };

  const toggleTheme = () => {
    const next = theme === "dark" ? "ivory" : "dark";
    setTheme(next);
  };

  return (
    <ThemeContext.Provider value={{ theme, toggleTheme, setTheme }}>
      {children}
    </ThemeContext.Provider>
  );
}

export function useTheme() {
  return useContext(ThemeContext);
}
