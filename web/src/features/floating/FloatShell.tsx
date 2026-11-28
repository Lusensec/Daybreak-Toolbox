import { useEffect, useRef, useState } from "react";
import { X } from "lucide-react";
import { connectBridge, fetchBridgeToken, sendCommand } from "../../services/ws";
import { bindMenuEvents } from "../menu/store";
import { FloatingMenuCanvas, renderMenuContent, isFixedMenu, menuDotColor } from "./menuContent";
import { FLOAT_MIN } from "./detachStore";
import "./FloatingWindow.css";

const BRIDGE_HOSTED = !import.meta.env.DEV;

/**
 * 原生浮动子窗口页面（v2.3.2）。
 *
 * 由 bridge/float_service.py 创建独立 pywebview 窗口加载：
 *   /tools/:menu/:nav?float=1&kind=menu|nav&key=...&label=...
 * 该页面不渲染 AppShell（无侧栏/顶栏/路由），只由「自绘标题栏 + 菜单画布」组成：
 *  - 标题栏拖动走 float.drag（Win32 原生拖动，松手才返回）；
 *  - 关闭 → float.close（后端销毁窗口 → 广播 float.closed 让主窗口收回按钮态）；
 *  - 右下角把手流式 float.resize；
 *  - 正文复用 FloatingMenuCanvas（kind=nav 时定位到该导航）或固定菜单页面。
 */
export default function FloatShell() {
  const q = new URLSearchParams(window.location.search);
  const key = q.get("key") ?? "";
  const rawKind = q.get("kind");
  const kind = rawKind === "nav" ? "nav" : rawKind === "browser" ? "browser" : "menu";
  const menu = q.get("menu") ?? "首页";
  const nav = q.get("nav") ?? "首页";
  const url = q.get("url") ?? "";
  const label = q.get("label") ?? (key || menu);
  const closeAfterResize = useRef<null | (() => void)>(null);

  // 桥接引导：取 token → 连 SSE → 拉菜单数据（与 AppShell 的生产模式逻辑一致）
  useEffect(() => {
    let cancelled = false;
    (async () => {
      let token = localStorage.getItem("daybreak.token") ?? "";
      if (BRIDGE_HOSTED) {
        const t = await fetchBridgeToken();
        if (t) {
          token = t;
          localStorage.setItem("daybreak.token", t);
        }
      }
      if (cancelled) return;
      try {
        await connectBridge({ token: token || undefined });
        bindMenuEvents();
      } catch {
        /* 连接失败由画布内的加载态呈现 */
      }
    })();
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    document.title = label;
  }, [label]);

  /** 标题栏拖动：移动超过 3px 才真正开始（避免干扰双击全屏）。
   *  开始前先问后端要当前矩形；若处于双击全屏态，后端会先还原到原尺寸并让光标落在
   *  标题栏同一相对位置，然后前端用「光标屏幕坐标 - 窗口原点」的固定偏移流式跟随。 */
  function onHeadPointerDown(e: React.PointerEvent<HTMLDivElement>) {
    if (e.pointerType === "mouse" && e.button !== 0) return;
    if ((e.target as HTMLElement).closest("button")) return;
    const head = e.currentTarget;
    const sx = e.screenX;
    const sy = e.screenY;
    const cx = e.clientX;
    const cy = e.clientY;
    const ratio = cx / Math.max(1, window.innerWidth);
    let started = false;
    let ready = false;
    let finished = false;
    let offX = 0;
    let offY = 0;
    let latest = { x: sx, y: sy };
    let queued = false;
    let inFlight = 0;
    let pending: { x: number; y: number } | null = null;
    try { head.setPointerCapture(e.pointerId); } catch { /* 旧浏览器 */ }

    // 至多一笔在途：慢 RTT 时合并中间帧（只保留最新坐标），避免拖动把请求堆满
    const flush = () => {
      if (!ready || inFlight > 0) return;
      const t = pending;
      pending = null;
      if (!t) return;
      inFlight += 1;
      void sendCommand("float.move", { key, x: t.x, y: t.y })
        .catch(() => {})
        .finally(() => {
          inFlight -= 1;
          if (pending) flush();
        });
    };
    const schedule = () => {
      queued = false;
      if (!ready) return;
      pending = { x: Math.round(latest.x - offX), y: Math.round(latest.y - offY) };
      flush();
    };
    const begin = async () => {
      // 兜底：以按下时的「屏幕坐标 - client 偏移」当作窗口原点
      let bx = sx - cx;
      let by = sy - cy;
      try {
        const r = await sendCommand(
          "float.drag_begin", { key, sx, sy, ratio, title_h: cy }, 5000,
        );
        const rect = (r?.rect ?? r) as { x?: number; y?: number };
        if (Number.isFinite(Number(rect.x))) bx = Number(rect.x);
        if (Number.isFinite(Number(rect.y))) by = Number(rect.y);
      } catch { /* 用兜底坐标 */ }
      if (finished) return;
      offX = sx - bx;
      offY = sy - by;
      ready = true;
      schedule();
    };
    const onMove = (ev: PointerEvent) => {
      latest = { x: ev.screenX, y: ev.screenY };
      if (!started) {
        if (Math.hypot(ev.screenX - sx, ev.screenY - sy) < 3) return;
        started = true;
        void begin();
        return;
      }
      if (queued) return;
      queued = true;
      requestAnimationFrame(schedule);
    };
    const teardown = (ev: PointerEvent) => {
      finished = true;
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", teardown);
      window.removeEventListener("pointercancel", teardown);
      try { head.releasePointerCapture(ev.pointerId); } catch { /* 忽略 */ }
      latest = { x: ev.screenX, y: ev.screenY };
      if (started && ready) {
        pending = { x: Math.round(latest.x - offX), y: Math.round(latest.y - offY) };
        flush(); // 补最后一帧，窗口精确停在松手位置
      }
    };
    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", teardown);
    window.addEventListener("pointercancel", teardown);
  }

  function closeSelf() {
    void sendCommand("float.close", { key })
      .catch(() => {})
      .finally(() => {
        try { window.close(); } catch { /* 忽略 */ }
      });
  }

  /** 右下角拉伸：rAF 节流发 float.resize（最小 420×300，后端再钳制上限） */
  function startResize(e: React.PointerEvent<HTMLDivElement>) {
    if (e.pointerType === "mouse" && e.button !== 0) return;
    e.preventDefault();
    e.stopPropagation();
    const sx = e.screenX;
    const sy = e.screenY;
    const w0 = window.innerWidth;
    const h0 = window.innerHeight;
    let lw = w0;
    let lh = h0;
    let queued = false;
    const send = () => {
      queued = false;
      void sendCommand("float.resize", { key, width: lw, height: lh }).catch(() => {});
    };
    const onMove = (ev: PointerEvent) => {
      lw = Math.max(FLOAT_MIN.w, Math.round(w0 + (ev.screenX - sx)));
      lh = Math.max(FLOAT_MIN.h, Math.round(h0 + (ev.screenY - sy)));
      if (queued) return;
      queued = true;
      requestAnimationFrame(send);
    };
    const teardown = () => {
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", teardown);
      window.removeEventListener("pointercancel", teardown);
      closeAfterResize.current = null;
    };
    closeAfterResize.current = teardown;
    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", teardown);
    window.addEventListener("pointercancel", teardown);
  }

  // 卸载时拆掉可能残留的拉伸监听（窗口被外部关闭）
  useEffect(() => () => { closeAfterResize.current?.(); }, []);

  return (
    <div className="float-shell">
      <div
        className="float-shell__head"
        onPointerDown={onHeadPointerDown}
        onDoubleClick={(e) => {
          if ((e.target as HTMLElement).closest("button")) return;
          void sendCommand("float.maximize", { key }).catch(() => {});
        }}
        title="按住拖动窗口 · 双击 全屏/还原"
      >
        <span className="float-window__dot" style={{ background: menuDotColor(menu) }} />
        <span className="float-window__title">{label}</span>
        <button className="float-window__close" title="关闭子窗口" onClick={closeSelf}>
          <X size={15} />
        </button>
      </div>
      <div
        className={"float-shell__body" + (kind === "browser" ? " float-shell__body--plain" : "")}
      >
        {kind === "browser" ? (
          <FloatBrowser floatKey={key} url={url} />
        ) : kind === "nav" ? (
          // 导航栏拖出的子窗口：只保留工具内容（不再重复导航行）
          <FloatingMenuCanvas menu={menu} initialNav={nav} showNav={false} />
        ) : isFixedMenu(menu) ? (
          renderMenuContent(menu)
        ) : (
          <FloatingMenuCanvas menu={menu} initialNav={nav} />
        )}
      </div>
      <div
        className="float-shell__grip"
        onPointerDown={startResize}
        title="拖动拉伸（最小 420×300）"
      />
    </div>
  );
}

/**
 * 浮动子窗口里的浏览器内容（拖出的浏览器标签）。
 *
 * 窗口本体的 WebView2 只负责绘制我们的 SPA；这里再把一个**独立的原生 WebView2**
 * 覆盖在占位 div 上（父窗体 = 本浮窗），目标网页是顶层文档，不受 X-Frame-Options 限制。
 * 原生不可用（dev / 服务形态 / 初始化失败）时回退 iframe。
 */
function FloatBrowser({ floatKey, url }: { floatKey: string; url: string }) {
  const frameRef = useRef<HTMLDivElement | null>(null);
  const [failed, setFailed] = useState(!url);

  useEffect(() => {
    const el = frameRef.current;
    if (!el || !url) return;
    let alive = true;
    let tries = 0;
    const read = () => {
      const r = el.getBoundingClientRect();
      if (r.width < 2 || r.height < 2) return null;
      return { x: r.left, y: r.top, width: r.width, height: r.height };
    };
    const attach = () => {
      if (!alive) return;
      const rect = read();
      if (!rect) {
        if (tries++ < 60) requestAnimationFrame(attach);
        else setFailed(true);
        return;
      }
      void sendCommand("browser.attach_float", { key: floatKey, url, rect }).catch(() => {
        if (alive) setFailed(true);
      });
    };
    const raf = requestAnimationFrame(attach);
    const sync = () => {
      const rect = read();
      if (rect) void sendCommand("browser.set_float_rect", { key: floatKey, rect }).catch(() => {});
    };
    const ro = new ResizeObserver(sync);
    ro.observe(el);
    window.addEventListener("resize", sync);
    return () => {
      alive = false;
      cancelAnimationFrame(raf);
      ro.disconnect();
      window.removeEventListener("resize", sync);
      void sendCommand("browser.hide_float", { key: floatKey }).catch(() => {});
    };
  }, [floatKey, url]);

  if (failed) {
    return <iframe className="float-shell__frame" src={url} title="网页" referrerPolicy="no-referrer" />;
  }
  return (
    <div className="float-shell__browser" ref={frameRef}>
      <span className="float-shell__browser-hint">正在加载页面…</span>
    </div>
  );
}
