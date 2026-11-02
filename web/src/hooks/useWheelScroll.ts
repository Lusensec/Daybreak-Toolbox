import { useEffect } from "react";

/**
 * 滚轮上下滑动 → 驱动容器左右滚动（菜单栏 / 导航栏行）。
 *  - 单行不换行，隐藏原生滑条，视觉干净
 *  - 只有容器确实横向溢出时才接管事件，纵向滚动不受影响
 *  - 用原生非 passive 监听（React onWheel 是 passive，preventDefault 无效）
 *
 * @param enabled 容器是否已渲染（条件渲染的容器首次渲染后 ref.current 才有效，
 *                必须靠 enabled 变化触发 effect 重跑，否则监听器挂不上）
 */
export function useWheelScrollHorizontal(
  ref: React.RefObject<HTMLElement | null>,
  enabled: boolean = true,
) {
  useEffect(() => {
    if (!enabled) return;
    const el = ref.current;
    if (!el) return;
    const onWheel = (e: WheelEvent) => {
      if (Math.abs(e.deltaY) <= Math.abs(e.deltaX)) return; // 横向触控板手势交给原生
      if (el.scrollWidth <= el.clientWidth) return;         // 无溢出不拦截
      e.preventDefault();
      el.scrollLeft += e.deltaY;
    };
    el.addEventListener("wheel", onWheel, { passive: false });
    return () => el.removeEventListener("wheel", onWheel);
  }, [ref, enabled]);
}
