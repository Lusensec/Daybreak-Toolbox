import { useState } from "react";

/**
 * 通用「角落拉伸把手」hook（模态框 / 浮动子窗口共用，pointer 事件，鼠标+触摸）。
 *
 * 尺寸归属调用方（inline style / store），本 hook 只管手势：
 *  - min 固定；max = 配置 max 与 视口（16px 边距）的较小者 —— 永远拉不出屏幕
 *  - resizing=true 可加 class（高亮把手 / 禁用过渡）
 *  - dir "se"（默认）：左上角固定，宽/高随指针外移增大
 *  - dir "sw"：右下角固定，左边缘随指针移动（左拉变宽），高度规则同 se
 *
 * 用法：
 *   const { onPointerDown, resizing } = useResize({
 *     min: { w: 680, h: 420 }, max: { w: 1600, h: 1000 },
 *     getStartSize: () => size ?? DEFAULT,
 *     onResize: (w, h) => setSize({ w, h }),
 *   });
 *   // 左下角把手（子窗口）：宽/高之外还要把 x 左移
 *   const sw = useResize({
 *     ..., dir: "sw",
 *     getStartLeft: () => pos.x,   // 手势开始时的左缘 x
 *     onX: (x) => move(x),         // 右缘不变 = 起始 x + 起始 w − 当前 w
 *   });
 *   <div className="resize-grip sw" onPointerDown={sw.onPointerDown} />
 */
export function useResize(opts: {
  min: { w: number; h: number };
  max: { w: number; h: number };
  getStartSize: () => { w: number; h: number };
  onResize: (w: number, h: number) => void;
  /** 把手方向："se" 右下角（默认，左上角固定）/ "sw" 左下角（左缘随指针，右缘固定） */
  dir?: "se" | "sw";
  /** sw 用：手势开始时的左缘 x（hook 在 pointerdown 时读取一次，全程无漂移） */
  getStartLeft?: () => number;
  /** sw 用：宽度算出后回写新的左缘 x（右缘 = 起始 x + 起始 w − 当前 w，恒定） */
  onX?: (x: number) => void;
}) {
  const [resizing, setResizing] = useState(false);
  const { min, max, getStartSize, onResize, dir = "se", getStartLeft, onX } = opts;

  const onPointerDown = (e: React.PointerEvent<HTMLElement>) => {
    if (e.pointerType === "mouse" && e.button !== 0) return;
    e.preventDefault();
    e.stopPropagation(); // 别触发容器（如子窗口）的 onPointerDown 置顶逻辑
    const grip = e.currentTarget;
    try { grip.setPointerCapture(e.pointerId); } catch { /* 旧浏览器 */ }
    const s = getStartSize();
    const sx = e.clientX;
    const sy = e.clientY;
    const left0 = dir === "sw" ? getStartLeft?.() : undefined;
    setResizing(true);

    const mv = (ev: PointerEvent) => {
      const maxW = Math.min(max.w, window.innerWidth - 16);
      const maxH = Math.min(max.h, window.innerHeight - 16);
      if (dir === "sw") {
        // 左缘跟手：指针左移变宽（与右下角镜像）；右缘恒为 left0 + s.w
        const w = Math.max(min.w, Math.min(maxW, s.w + (sx - ev.clientX)));
        const h = Math.max(min.h, Math.min(maxH, s.h + (ev.clientY - sy)));
        onResize(w, h);
        if (left0 !== undefined) onX?.(left0 + s.w - w);
      } else {
        onResize(
          Math.max(min.w, Math.min(maxW, s.w + (ev.clientX - sx))),
          Math.max(min.h, Math.min(maxH, s.h + (ev.clientY - sy))),
        );
      }
    };
    const up = (ev: PointerEvent) => {
      grip.removeEventListener("pointermove", mv);
      grip.removeEventListener("pointerup", up);
      grip.removeEventListener("pointercancel", up);
      try { grip.releasePointerCapture(ev.pointerId); } catch { /* 忽略 */ }
      setResizing(false);
    };
    grip.addEventListener("pointermove", mv);
    grip.addEventListener("pointerup", up);
    grip.addEventListener("pointercancel", up);
  };

  return { onPointerDown, resizing };
}
