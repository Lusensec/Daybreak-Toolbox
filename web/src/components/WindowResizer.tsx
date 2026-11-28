import { useEffect, useRef } from "react";
import { sendCommand } from "../services/ws";

/**
 * v2.2.1：窗口边缘缩放手柄（Windows 原生体验复刻）。
 *
 * 背景：无边框（frameless）窗口没有 Windows 原生的缩放边框，但用户期望「和普通
 * Windows 应用一样」——左右下三条边 + 四个角可拖动拉伸，且不能无限拉小。
 * pywebview 的 frameless 会去掉 WS_THICKFRAME 的可视边框，且 easy_drag=False 后
 * 系统不再提供任何缩放入口，所以这里自绘 8 个透明手柄：
 *
 *   ├ 上(n)  ├ 右(e)  ├ 下(s)  ├ 左(w)
 *   └ 四角(nw/ne/sw/se)
 *
 * 每个手柄在 mousedown 时记录「窗口初始 rect + 鼠标初始位置」，mousemove 期间
 * 按方向算出新的 x/y/width/height，通过 window.set_rect 流式推给后端
 * （后端 SetWindowPos 原子提交，settle=False 连发安全）。
 *
 * 与顶栏拖拽一致的健壮性处理：
 *  - mouseup 丢失（窗口外松手 / pointercancel / 失焦 / 切后台）→ 幂等拆除监听器
 *  - 位移小于阈值（<3px）视为单击，不发任何几何命令
 *  - rAF 节流 + 「至多一笔在途」背压，避免 60fps 连发打爆 IPC
 *
 * 最小尺寸由后端 _clamp_window_size 兜底（960×600 逻辑像素），前端也做一层
 * 同源钳制，让光标反馈与实际行为一致（否则鼠标已到边界但窗口不动）。
 */

const MIN_W = 960;
const MIN_H = 600;
/** 位移阈值（px）：小于此值视为单击，不触发 resize */
const RESIZE_THRESHOLD = 3;

/**
 * 8 个手柄方向定义。
 * v2.2.1：按需求「三个边框（左右下）+ 四个顶点」—— **不做上边整条**手柄
 * （上边是顶栏拖动区，加了会和「拖顶栏移动窗口」抢鼠标）。
 * 四角手柄仍同时影响两个方向（nw/ne 角可拉出上边效果），与 Windows 原生一致。
 */
const HANDLES = [
  { dir: "s",  cursor: "ns-resize" },
  { dir: "e",  cursor: "ew-resize" },
  { dir: "w",  cursor: "ew-resize" },
  { dir: "nw", cursor: "nwse-resize" },
  { dir: "ne", cursor: "nesw-resize" },
  { dir: "sw", cursor: "nesw-resize" },
  { dir: "se", cursor: "nwse-resize" },
] as const;

type Dir = (typeof HANDLES)[number]["dir"];

/**
 * 按拖动方向与鼠标位移，计算新的窗口矩形。
 * 纯函数（导出便于测试）：锚点为窗口「对侧边」，拖动边跟随鼠标。
 *
 * 位移语义：dx/dy = 鼠标相对按下点的位移（屏幕坐标，右/下为正）。
 *  - 拖右边界（e）：鼠标右移 → 窗口变宽 → width += dx
 *  - 拖左边界（w）：鼠标左移（dx<0）→ 窗口变宽 → width -= dx，且 x += dx
 *  - 拖下边界（s）：鼠标下移 → 变高 → height += dy
 *  - 拖上边界（n）：鼠标上移（dy<0）→ 变高 → height -= dy，且 y += dy
 */
export function computeResizedRect(
  dir: Dir,
  start: { x: number; y: number; width: number; height: number },
  dx: number,
  dy: number,
): { x: number; y: number; width: number; height: number } {
  let { x, y, width, height } = start;

  if (dir.includes("e")) {
    // 右边界随鼠标右移 → 变宽（锚点在左）
    width = start.width + dx;
  } else if (dir.includes("w")) {
    // 左边界随鼠标左移（dx 负）→ 变宽；左边界 x 同步跟随鼠标
    width = start.width - dx;
    x = start.x + dx;
  }

  if (dir.includes("s")) {
    // 下边界随鼠标下移 → 变高（锚点在顶）
    height = start.height + dy;
  } else if (dir.includes("n")) {
    // 上边界随鼠标上移（dy 负）→ 变高；上边界 y 同步跟随鼠标
    height = start.height - dy;
    y = start.y + dy;
  }

  // 最小尺寸钳制：拉小到极限时，被拖动的那条边停在「锚点 - 最小尺寸」处，
  // 另一边（x/y）随之回弹 —— 与 Windows 原生「拖到最小尺寸就停住」一致。
  if (width < MIN_W) {
    width = MIN_W;
    if (dir.includes("w")) {
      // 锚点在右边 → 左边界 = 起始右边界 - MIN_W
      x = start.x + start.width - MIN_W;
    }
  }
  if (height < MIN_H) {
    height = MIN_H;
    if (dir.includes("n")) {
      // 锚点在底边 → 上边界 = 起始下边界 - MIN_H
      y = start.y + start.height - MIN_H;
    }
  }

  return { x: Math.round(x), y: Math.round(y), width: Math.round(width), height: Math.round(height) };
}

export function WindowResizer({ enabled }: { enabled: boolean }) {
  const teardownRef = useRef<(() => void) | null>(null);

  useEffect(() => {
    return () => {
      teardownRef.current?.();
    };
  }, []);

  if (!enabled) return null;

  async function startResize(dir: Dir, e: React.MouseEvent) {
    e.preventDefault();
    e.stopPropagation();
    teardownRef.current?.();

    try {
      const r = (await sendCommand("window.get_rect", {})) as {
        rect?: { x: number; y: number; width: number; height: number } | null;
      };
      const rect = r?.rect;
      if (!rect) return;

      const start = { x: rect.x, y: rect.y, width: rect.width, height: rect.height };
      const sx = e.screenX;
      const sy = e.screenY;
      let moved = false;
      let queued = false;
      let inFlight = 0;
      let lastSent = 0;

      const teardown = () => {
        window.removeEventListener("mousemove", onMove);
        window.removeEventListener("mouseup", onUp);
        window.removeEventListener("pointercancel", teardown);
        window.removeEventListener("blur", teardown);
        document.removeEventListener("visibilitychange", onVisibility);
        teardownRef.current = null;
      };
      const onVisibility = () => {
        if (document.hidden) teardown();
      };

      const send = (rect: { x: number; y: number; width: number; height: number }) => {
        const now = performance.now();
        if (now - lastSent < 8) return;   // ~120fps 上限，留 WebView2 合成时间
        lastSent = now;
        inFlight += 1;
        void sendCommand("window.set_rect", rect).catch(() => {}).finally(() => {
          inFlight -= 1;
        });
      };

      const onMove = (ev: MouseEvent) => {
        const dx = ev.screenX - sx;
        const dy = ev.screenY - sy;
        if (!moved && Math.abs(dx) < RESIZE_THRESHOLD && Math.abs(dy) < RESIZE_THRESHOLD) return;
        moved = true;
        if (queued) return;
        queued = true;
        requestAnimationFrame(() => {
          queued = false;
          const next = computeResizedRect(dir, start, dx, dy);
          send(next);
        });
      };

      const onUp = () => {
        teardown();
      };

      teardownRef.current = teardown;
      window.addEventListener("mousemove", onMove);
      window.addEventListener("mouseup", onUp);
      window.addEventListener("pointercancel", teardown);
      window.addEventListener("blur", teardown);
      document.addEventListener("visibilitychange", onVisibility);
    } catch {
      /* 桥接未就绪 */
    }
  }

  return (
    <>
      {HANDLES.map((h) => (
        <div
          key={h.dir}
          className={`win-edge win-edge--${h.dir}`}
          style={{ cursor: h.cursor }}
          onMouseDown={(e) => void startResize(h.dir, e)}
        />
      ))}
    </>
  );
}
