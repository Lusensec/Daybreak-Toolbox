import { useCallback, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { useDetachStore, clampFloatPos, FLOAT_W, FLOAT_H } from "./detachStore";

/**
 * 菜单按钮「栏内重排 / 拖出脱离为子窗口」统一拖拽 hook（pointer 事件，鼠标+触摸）。
 *
 * 手势（每个菜单按钮挂一个实例）：
 *  - 按住移动 ≥4px 才进入拖拽（更短的移动视为普通点击）
 *  - 拖拽中：ghost 跟手；指针悬停其它菜单按钮 → 该按钮高亮「插入位」（共享 hoverTarget）
 *  - 指针**离开顶栏**（外扩 10px 包围盒之外）→ ghost 变虚线「松开脱离为子窗口」
 *  - 松手：脱离区 → 在松手处开子窗口（钳制视口内）；栏内且 reorderable →
 *         onInBarDrop(目标菜单名)（调用方把名字换算成下标，沿用旧 drop 的插缝算法）；
 *         其余 → 无操作（固定菜单栏内松手=不重排）
 *
 * 关键实现：**pointerdown 立即 setPointerCapture** + move/up 监听挂 **window**。
 * 指针一旦离开按钮，事件就落到光标下的元素（若监听挂按钮自身则永远收不到 → 死锁）；
 * 立即捕获 + window 监听保证无论光标在哪都能收到 move/up。
 *
 * @returns
 *  - startDrag  绑按钮 onPointerDown
 *  - suppressClick 绑按钮 onClick：上一次是拖拽则吞掉 click（拖完不触发点击导航）
 *  - ghost  渲染在按钮组件内（portal 到 body）
 */
export function useDetachDrag(opts: {
  name: string;
  color?: string;
  /** 顶栏容器（判定「栏内/栏外」的参照 rect） */
  barRef: React.RefObject<HTMLElement | null>;
  reorderable?: boolean;
  onInBarDrop?: (targetName: string) => void;
}) {
  const [drag, setDrag] = useState<null | { x: number; y: number; detach: boolean }>(null);
  const dragged = useRef(false);
  const { name, color, barRef, reorderable, onInBarDrop } = opts;
  const store = useDetachStore;
  /** 自己是否正被悬停（= 拖别的菜单时的「插入位」高亮目标） */
  const hoverTarget = store((s) => s.hoverTarget);
  const hoverMe = hoverTarget === name;

  const startDrag = useCallback(
    (e: React.PointerEvent<HTMLElement>) => {
      if (e.pointerType === "mouse" && e.button !== 0) return;
      const btn = e.currentTarget;
      const sx = e.clientX;
      const sy = e.clientY;
      let started = false;
      let last = { x: sx, y: sy };
      // 立即捕获：后续 move/up 始终指向按钮，光标移出也能收到
      try { btn.setPointerCapture(e.pointerId); } catch { /* 旧浏览器 */ }

      const outside = (x: number, y: number) => {
        const r = barRef.current?.getBoundingClientRect();
        if (!r) return false;
        const m = 10;
        return x < r.left - m || x > r.right + m || y < r.top - m || y > r.bottom + m;
      };

      const move = (ev: PointerEvent) => {
        last = { x: ev.clientX, y: ev.clientY };
        if (!started) {
          if (Math.hypot(ev.clientX - sx, ev.clientY - sy) < 4) return;
          started = true;
          dragged.current = true;
        }
        ev.preventDefault();
        // 悬停高亮：指针下方的菜单按钮（非自己）= 插入位
        let target: string | null = null;
        if (!outside(ev.clientX, ev.clientY) && reorderable) {
          const el = document.elementFromPoint(ev.clientX, ev.clientY) as HTMLElement | null;
          const idx = el?.closest?.("[data-detach-btn]") as HTMLElement | null;
          if (idx && idx.dataset.detachBtn && idx.dataset.detachBtn !== name) target = idx.dataset.detachBtn;
        }
        store.getState().setHoverTarget(target);
        setDrag({ x: last.x, y: last.y, detach: outside(last.x, last.y) });
      };

      const up = (ev: PointerEvent) => {
        window.removeEventListener("pointermove", move);
        window.removeEventListener("pointerup", up);
        window.removeEventListener("pointercancel", up);
        try { btn.releasePointerCapture(ev.pointerId); } catch { /* 忽略 */ }
        if (!started) { setDrag(null); return; }
        const { x, y } = last;
        store.getState().setHoverTarget(null);
        if (outside(x, y)) {
          const p = clampFloatPos(x - FLOAT_W / 2, y - FLOAT_H / 2);
          store.getState().open(name, p.x, p.y);
        } else if (reorderable && onInBarDrop) {
          const el = document.elementFromPoint(x, y) as HTMLElement | null;
          const idx = el?.closest?.("[data-detach-btn]") as HTMLElement | null;
          const t = idx?.dataset.detachBtn;
          if (t && t !== name) onInBarDrop(t);
        }
        setDrag(null);
        // dragged 标志留给紧随的 click（拖拽后的 click 要吞）；宏任务清位，避免误吞下一次正常点击
        setTimeout(() => { dragged.current = false; }, 0);
      };

      window.addEventListener("pointermove", move);
      window.addEventListener("pointerup", up);
      window.addEventListener("pointercancel", up);
    },
    [name, barRef, reorderable, onInBarDrop, store],
  );

  /** 按钮 onClick 首行调用：刚拖拽过 → 返回 true（调用方直接 return，吞掉 click） */
  const suppressClick = useCallback(() => {
    if (dragged.current) {
      dragged.current = false;
      return true;
    }
    return false;
  }, []);

  const ghost = drag
    ? createPortal(
        <div
          className={"float-ghost" + (drag.detach ? " float-ghost--detach" : "")}
          style={{ left: drag.x - 40, top: drag.y - 18 }}
        >
          <span className="float-ghost__dot" style={{ background: color || "#2980b9" }} />
          <span>{name}</span>
          {drag.detach ? <em>松开脱离为子窗口</em> : null}
        </div>,
        document.body,
      )
    : null;

  return { startDrag, suppressClick, ghost, hoverMe };
}
