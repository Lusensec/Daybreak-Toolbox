/**
 * 破晓·工具箱 —— 设计令牌（TS 镜像）
 *
 * 与 tokens.css 一一对应；在需要 JS 侧直接取色值的地方使用
 *（如 xterm.js 初始化、canvas 绘图、动态生成 DOM 样式）。
 *
 * 来源：ui_theme.py COLORS / DARK（2026-10 v1.2.1 扩展版）
 */

export interface Palette {
  bg: string;
  panel: string;
  border: string;
  text: string;
  muted: string;
  accent: string;
  accentHi: string;
  accentLo: string;
  success: string;
  warn: string;
  error: string;
  consoleBg: string;
  consoleFg: string;
  cmdFg: string;
  outFg: string;
  scroll: string;
  headingBg: string;
  headingActive: string;
  noteBg: string;
  noteFg: string;
  noteGutterBg: string;
  noteGutterFg: string;
  noteLineHl: string;
  noteCursor: string;
  noteSel: string;
  noteSelFg: string;
  tintBlue: string;
  tintGreen: string;
  entryBg: string;
}

export const LIGHT: Palette = {
  bg: "#f4f6f8",
  panel: "#ffffff",
  border: "#d9dde3",
  text: "#202124",
  muted: "#5f6368",
  accent: "#1a73e8",
  accentHi: "#2b86f5",
  accentLo: "#b6c5e0",
  success: "#188038",
  warn: "#f9ab00",
  error: "#d93025",
  consoleBg: "#ffffff",
  consoleFg: "#202124",
  cmdFg: "#1a73e8",
  outFg: "#202124",
  scroll: "#cfd8dc",
  headingBg: "#e8eaed",
  headingActive: "#dde2e8",
  noteBg: "#f4f6f8",
  noteFg: "#202124",
  noteGutterBg: "#e8eaed",
  noteGutterFg: "#9aa0a6",
  noteLineHl: "#d1e7ff",
  noteCursor: "#1a73e8",
  noteSel: "#a8d1ff",
  noteSelFg: "#000000",
  tintBlue: "#e8f0fe",
  tintGreen: "#e6f4ea",
  entryBg: "#ffffff",
};

export const DARK: Palette = {
  bg: "#1e1f24",
  panel: "#262830",
  border: "#3a3d46",
  text: "#e6e6e6",
  muted: "#9aa0a6",
  accent: "#4f9cf9",
  accentHi: "#6cb0ff",
  accentLo: "#33425a",
  success: "#34a853",
  warn: "#fdd663",
  error: "#f28b82",
  consoleBg: "#14151a",
  consoleFg: "#e6e6e6",
  cmdFg: "#82d1ff",
  outFg: "#e6e6e6",
  scroll: "#44474f",
  headingBg: "#31343d",
  headingActive: "#3a3d46",
  noteBg: "#1e1f24",
  noteFg: "#e6e6e6",
  noteGutterBg: "#262830",
  noteGutterFg: "#9aa0a6",
  noteLineHl: "#2a3a52",
  noteCursor: "#4f9cf9",
  noteSel: "#2a4a75",
  noteSelFg: "#ffffff",
  tintBlue: "#263447",
  tintGreen: "#24382e",
  entryBg: "#1e1f24",
};

export type Theme = "light" | "dark";

/** 用户主题选择（含跟随系统）；解析到 DOM 的 data-theme 仍是 light/dark。 */
export type ThemeChoice = "light" | "dark" | "system";

export function getPalette(theme: Theme): Palette {
  return theme === "dark" ? DARK : LIGHT;
}

/** 读取当前 DOM 上的主题（默认 light） */
export function activeTheme(): Theme {
  if (typeof document === "undefined") return "light";
  return document.documentElement.dataset.theme === "dark" ? "dark" : "light";
}

export function activePalette(): Palette {
  return getPalette(activeTheme());
}
