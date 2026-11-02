import { useEffect } from "react";
import type { ReactNode } from "react";
import { activePalette } from "../theme/tokens";

/** 极简占位页骨架：Phase 3 各面板逐个替换 */
export function PlaceholderPage({ title, hint }: { title: string; hint?: ReactNode }) {
  const p = activePalette();
  // 主题切换时强制刷新以重算 JS 侧取色（如 xterm 初始化色）
  useEffect(() => { /* no-op for placeholder; real panels hook their own */ }, [p]);

  return (
    <div className="card" style={{ borderLeftColor: p.accent, borderLeftWidth: 4 }}>
      <h1 style={{ margin: "0 0 4px", fontSize: 18, color: "var(--text)" }}>{title}</h1>
      {hint ? <p style={{ margin: 0, color: "var(--muted)", fontSize: 13 }}>{hint}</p> : null}
    </div>
  );
}
