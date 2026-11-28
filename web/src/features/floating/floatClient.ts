import { sendCommand, subscribeEvent } from "../../services/ws";
import { useDetachStore, FLOAT_W, FLOAT_H } from "./detachStore";

/**
 * v2.3.2：菜单/导航拖出顶栏后的「脱离」入口。
 *
 * 首选后端原生浮动窗口（bridge/float_service.py，独立 OS 窗口）：
 *  - 能真正拖出主窗口，也不会被主窗口内的原生 WebView2 浏览器遮挡；
 *  - 创建成功后 detachStore 只保留「已脱离」态（native=true），不再渲染 HTML 浮层。
 *
 * 原生窗口不可用（dev / 服务形态 / 非 Windows / 创建失败）时，自动回退到旧的 HTML 浮层，
 * 保证开发与降级路径行为不丢。
 */
export interface FloatSpec {
  /** 唯一标识：菜单=菜单名；导航=`${菜单}::${导航}`；浏览器标签=`browser::${tab.id}` */
  key: string;
  label: string;
  kind: "menu" | "nav" | "browser";
  menu: string;
  nav: string;
  /** kind=browser 时的目标网页地址 */
  url?: string;
  /** 松手处相对主窗口视口的 CSS 坐标 */
  x: number;
  y: number;
  width?: number;
  height?: number;
}

/** 拖出脱离：返回 true=原生窗口，false=浮层回退 */
export async function detachToFloat(spec: FloatSpec): Promise<boolean> {
  try {
    await sendCommand(
      "float.create",
      {
        key: spec.key,
        label: spec.label,
        kind: spec.kind,
        menu: spec.menu,
        nav: spec.nav,
        x: spec.x,
        y: spec.y,
        width: spec.width ?? FLOAT_W,
        height: spec.height ?? FLOAT_H,
        url: spec.url ?? "",
      },
      30000,
    );
    useDetachStore.getState().markNative(spec.key);
    return true;
  } catch {
    // 回退：在松手处开旧的 HTML 浮层（与 v2.3.1 行为一致）
    useDetachStore.getState().open(spec.key, spec.x - FLOAT_W / 2, spec.y - FLOAT_H / 2);
    return false;
  }
}

/** 收回已脱离的菜单/导航（原生窗口同时请求后端销毁；float.closed 事件会再做一次幂等清理） */
export function closeFloat(key: string): void {
  const d = useDetachStore.getState().detached[key];
  if (d?.native) {
    void sendCommand("float.close", { key }).catch(() => {});
  }
  useDetachStore.getState().close(key);
}

/** 订阅 `float.closed`（用户在浮窗标题栏点 × / OS 关闭窗口）→ 主窗口收回「已脱离」态 */
export function bindFloatEvents(): () => void {
  return subscribeEvent("float.closed", (p) => {
    const key = String((p as { key?: unknown } | null)?.key ?? "");
    if (key) useDetachStore.getState().close(key);
  });
}
