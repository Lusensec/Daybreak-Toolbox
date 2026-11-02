import { useCallback, useEffect, useRef, useState } from "react";

/**
 * 通用「模态框可拖拽」hook（项目约定：以后所有模态框/对话框一律用它实现拖拽）。
 *
 * 用法（面板本体挂 panelRef，标题栏/把手挂 handleRef）：
 *   const panelRef = useRef<HTMLDivElement>(null);
 *   const headRef  = useRef<HTMLDivElement>(null);
 *   const { dragging, handleProps } = useDraggable(panelRef, headRef);
 *   <div ref={panelRef} className="modal">
 *     <header ref={headRef} {...handleProps}>标题</header>
 *   </div>
 *
 * 语义：
 *  - 在把手上按住（鼠标左键/触摸）拖动 → 面板跟随位移；位移用 transform 实现，
 *    不破坏 mask 的 flex 居中布局；面板关闭（unmount）自动复位
 *  - 双击把手 → 复位到居中
 *  - 把手内的交互元素（button/a/input/select/textarea，如关闭按钮）不触发拖拽
 *  - 视口收拢：面板不会被拖出屏幕（12px 安全边距）；窗口 resize 时自动重新收拢
 *  - 触摸可用：把手 CSS 需配 touch-action: none（见 .settings-modal__head 注释）
 *
 * @returns dragging 拖拽进行中（可加 class / 禁用过渡）；handleProps 展开到把手元素
 */
export function useDraggable(
  panelRef: React.RefObject<HTMLDivElement | null>,
  headRef: React.RefObject<HTMLDivElement | null>,
) {
  const [dragging, setDragging] = useState(false);
  const start = useRef({ x: 0, y: 0, ox: 0, oy: 0 });
  const offset = useRef({ x: 0, y: 0 });

  const apply = useCallback(() => {
    const el = panelRef.current;
    if (!el) return;
    const { x, y } = offset.current;
    el.style.transform = x || y ? `translate(${x}px, ${y}px)` : "";
  }, [panelRef]);

  /** 把 offset 收拢回「面板不出视口」范围（面板中心≈视口中心，mask flex 居中）。 */
  const clamp = useCallback(() => {
    const el = panelRef.current;
    if (!el) return;
    const r = el.getBoundingClientRect(); // 宽高不受 translate 影响
    const pad = 12;
    const maxX = Math.max(0, (window.innerWidth - r.width) / 2 - pad);
    const maxY = Math.max(0, (window.innerHeight - r.height) / 2 - pad);
    offset.current.x = Math.min(maxX, Math.max(-maxX, offset.current.x));
    offset.current.y = Math.min(maxY, Math.max(-maxY, offset.current.y));
  }, [panelRef]);

  useEffect(() => {
    const onResize = () => { clamp(); apply(); };
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, [clamp, apply]);

  const onPointerDown = useCallback((e: React.PointerEvent<HTMLElement>) => {
    // 交互元素（关闭按钮 / 下拉 / 输入框）上不触发拖拽，避免吃掉 click
    if ((e.target as HTMLElement).closest("button, a, input, select, textarea")) return;
    if (e.pointerType === "mouse" && e.button !== 0) return;
    const head = headRef.current;
    if (!head || !panelRef.current) return;
    e.preventDefault();
    head.setPointerCapture(e.pointerId); // move/up 被重定向到 head，哪怕指针滑出面板
    start.current = { x: e.clientX, y: e.clientY, ox: offset.current.x, oy: offset.current.y };
    setDragging(true);
    const move = (ev: PointerEvent) => {
      offset.current.x = start.current.ox + (ev.clientX - start.current.x);
      offset.current.y = start.current.oy + (ev.clientY - start.current.y);
      clamp();
      apply();
    };
    const up = (ev: PointerEvent) => {
      if (head.hasPointerCapture(ev.pointerId)) head.releasePointerCapture(ev.pointerId);
      head.removeEventListener("pointermove", move);
      head.removeEventListener("pointerup", up);
      head.removeEventListener("pointercancel", up);
      setDragging(false);
    };
    head.addEventListener("pointermove", move);
    head.addEventListener("pointerup", up);
    head.addEventListener("pointercancel", up);
  }, [panelRef, headRef, apply, clamp]);

  const onDoubleClick = useCallback(() => {
    offset.current = { x: 0, y: 0 };
    apply();
  }, [apply]);

  return { dragging, handleProps: { onPointerDown, onDoubleClick } as const };
}
