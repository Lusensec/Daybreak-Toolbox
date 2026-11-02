import { useCallback, useRef } from "react";
import { X } from "lucide-react";
import { useDetachStore, clampFloatPos, FLOAT_MIN, FLOAT_MAX } from "./detachStore";
import { useResize } from "../../hooks/useResize";
import { renderMenuContent, menuDotColor } from "./menuContent";
import "./FloatingWindow.css";

/**
 * 菜单「子窗口」宿主：渲染所有已脱离的菜单（detached 键序 + zOrder 定层）。
 * 挂在 AppShell 顶层；纯 UI 状态（刷新即全部收回栏内）。
 */
export function FloatingWindowHost() {
  // 选择器必须返回**稳定引用**（detached 对象本身，仅 open/close/move/resize 时变）。
  // 不能在此 Object.keys（每次返回新数组 → useSyncExternalStore 快照恒变 → 无限渲染 React #185）
  const detached = useDetachStore((s) => s.detached);
  const names = Object.keys(detached);
  if (names.length === 0) return null;
  return (
    <>
      {names.map((n) => (
        <FloatingWindow key={n} name={n} />
      ))}
    </>
  );
}

/**
 * 单个子窗口：标题栏（菜单色点 + 名称 + ✕收回）可拖移；**右下角 / 左下角把手可拉伸**
 * （min FLOAT_MIN / max FLOAT_MAX，且不超过视口；右下角左上固定，左下角右缘固定；尺寸存 detachStore，与位置同生命周期）。
 * 定位模型：固定左上角坐标（detachStore.detached），pointer 拖标题实时 move。
 */
export function FloatingWindow({ name }: { name: string }) {
  const pos = useDetachStore((s) => s.detached[name]);
  const z = useDetachStore((s) => s.zIndexOf(name));
  const close = useDetachStore((s) => s.close);
  const focus = useDetachStore((s) => s.focus);
  const headRef = useRef<HTMLDivElement>(null);

  const startMove = useCallback(
    (e: React.PointerEvent<HTMLDivElement>) => {
      if (e.pointerType === "mouse" && e.button !== 0) return;
      if ((e.target as HTMLElement).closest("button")) return; // 关闭按钮不触发拖移
      const head = headRef.current;
      const st = useDetachStore.getState();
      const p0 = st.detached[name];
      if (!head || !p0) return;
      st.focus(name);
      const sx = e.clientX;
      const sy = e.clientY;
      const ox = p0.x;
      const oy = p0.y;
      try { head.setPointerCapture(e.pointerId); } catch { /* 旧浏览器 */ }
      const mv = (ev: PointerEvent) => {
        const c = clampFloatPos(ox + (ev.clientX - sx), oy + (ev.clientY - sy), p0.w, p0.h);
        st.move(name, c.x, c.y);
      };
      const up = (ev: PointerEvent) => {
        head.removeEventListener("pointermove", mv);
        head.removeEventListener("pointerup", up);
        head.removeEventListener("pointercancel", up);
        try { head.releasePointerCapture(ev.pointerId); } catch { /* 忽略 */ }
      };
      head.addEventListener("pointermove", mv);
      head.addEventListener("pointerup", up);
      head.addEventListener("pointercancel", up);
    },
    [name, focus],
  );

  // 右下角拉伸：尺寸写回 store（与位置同生命周期，刷新收回）
  const se = useResize({
    min: FLOAT_MIN,
    max: FLOAT_MAX,
    getStartSize: () => useDetachStore.getState().detached[name] ?? { w: FLOAT_MIN.w, h: FLOAT_MIN.h },
    onResize: (w, h) => useDetachStore.getState().resize(name, w, h),
  });
  // 左下角拉伸：宽/高规则同右下角，但左缘跟手（右缘恒定）→ x 也写回 store
  const sw = useResize({
    min: FLOAT_MIN,
    max: FLOAT_MAX,
    dir: "sw",
    getStartSize: () => useDetachStore.getState().detached[name] ?? { w: FLOAT_MIN.w, h: FLOAT_MIN.h },
    getStartLeft: () => useDetachStore.getState().detached[name]?.x ?? 0,
    onResize: (w, h) => useDetachStore.getState().resize(name, w, h),
    onX: (x) => {
      const d = useDetachStore.getState().detached[name];
      if (d) useDetachStore.getState().move(name, x, d.y);
    },
  });
  const resizing = se.resizing || sw.resizing;

  if (!pos) return null;

  return (
    <div
      className={"float-window" + (resizing ? " is-resizing" : "")}
      style={{ left: pos.x, top: pos.y, width: pos.w, height: pos.h, zIndex: z }}
      onPointerDown={() => focus(name)}
    >
      <div className="float-window__head" ref={headRef} onPointerDown={startMove}>
        <span className="float-window__dot" style={{ background: menuDotColor(name) }} />
        <span className="float-window__title">{name}</span>
        <button className="float-window__close" title="收回菜单栏" onClick={() => close(name)}>
          <X size={15} />
        </button>
      </div>
      <div className="float-window__body">{renderMenuContent(name)}</div>
      {/* 右下角拉伸把手（min 420x300 / max 1400x900，且不超过视口） */}
      <div
        className={"resize-grip" + (se.resizing ? " is-resizing" : "")}
        onPointerDown={se.onPointerDown}
        title="拖动拉伸（最小 420x300）"
      />
      {/* 左下角拉伸把手：左缘跟手（右缘不变），宽/高限制同上 */}
      <div
        className={"resize-grip sw" + (sw.resizing ? " is-resizing" : "")}
        onPointerDown={sw.onPointerDown}
        title="左下拖动拉伸（最小 420x300）"
      />
    </div>
  );
}
