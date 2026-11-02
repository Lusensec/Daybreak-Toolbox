import {
  createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode,
} from "react";

/** 用户选择的主题（持久化）：浅色 / 深色 / 跟随系统。 */
export type ThemeChoice = "light" | "dark" | "system";

interface ThemeCtx {
  /** 用户当前选择（含 system）。 */
  theme: ThemeChoice;
  /** 解析后的实际深色态（system 时随系统深浅色实时切换）。 */
  isDark: boolean;
  /** 快捷翻转：light↔dark；若当前是 system 则切到「与解析后相反」的固定主题。 */
  toggle: () => void;
  set: (t: ThemeChoice) => void;
}

const ThemeContext = createContext<ThemeCtx | null>(null);
const LS_KEY = "daybreak.theme";

/** 解析「跟随系统」当前应落到的浅/深色。 */
function systemDark(): boolean {
  return typeof window !== "undefined" &&
    !!window.matchMedia &&
    window.matchMedia("(prefers-color-scheme: dark)").matches;
}

function readInitial(): ThemeChoice {
  const saved = typeof localStorage !== "undefined" ? localStorage.getItem(LS_KEY) : null;
  // 首次启动（无本地存储）默认「跟随系统」，按 OS 深浅色决定；之后持久化用户选择
  return saved === "dark" || saved === "light" || saved === "system" ? saved : "system";
}

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [choice, setChoice] = useState<ThemeChoice>(readInitial);
  // 当 choice === "system" 时，记录系统当前深浅，供 matchMedia 变化时实时更新
  const [sysDark, setSysDark] = useState(systemDark);

  // 系统深浅色变化：仅跟随系统模式下同步，其余保持不变
  useEffect(() => {
    if (typeof window === "undefined" || !window.matchMedia) return;
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    const onChange = (e: MediaQueryListEvent) => setSysDark(e.matches);
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, []);

  // 解析后的实际深色态
  const isDark = choice === "system" ? sysDark : choice === "dark";

  useEffect(() => {
    document.documentElement.dataset.theme = isDark ? "dark" : "light";
    try { localStorage.setItem(LS_KEY, choice); } catch { /* ignore */ }
  }, [isDark, choice]);

  const set = useCallback((t: ThemeChoice) => setChoice(t), []);
  const toggle = useCallback(() => {
    setChoice((c) => {
      if (c === "system") return (systemDark() ? "light" : "dark");
      return c === "dark" ? "light" : "dark";
    });
  }, []);

  const value = useMemo<ThemeCtx>(() => ({ theme: choice, isDark, toggle, set }), [choice, isDark, toggle, set]);
  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
}

export function useTheme(): ThemeCtx {
  const ctx = useContext(ThemeContext);
  if (!ctx) throw new Error("useTheme 必须在 <ThemeProvider> 内使用");
  return ctx;
}
