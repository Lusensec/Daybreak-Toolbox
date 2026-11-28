/**
 * 破晓·工具箱 —— 前端桥接客户端（v2.1.4：HTTP + SSE，替换原 WebSocket）
 *
 * 为什么改：
 *  - 后端已把 FastAPI/uvicorn/WebSocket 换掉（省 ~13MB 与一段启动开销），
 *    通信退化成「一条 POST /api/rpc + 一条 GET /api/events(SSE)」；
 *  - 对外导出签名保持不变（connectBridge / sendCommand / subscribeEvent / fetchBridgeToken /
 *    disconnectBridge / useConnStore），所有调用点无需改动。
 *
 * 信封与 bridge/server.py 对齐（仍是旧 WS 那套，故事件订阅与错误码逻辑照旧）：
 *   请求 {"v":1,"id","type","payload"} → 响应 {"v":1,"id","type":"ack|err","payload"}
 *   事件 {"v":1,"type","payload"}      → SSE 的 data: 行
 */
import { create } from "zustand";

export type WsStatus = "disconnected" | "connecting" | "online" | "reconnecting";

interface ConnState {
  status: WsStatus;
  lastError: string | null;
  /** 服务端广播事件的订阅表（event -> handlers） */
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  _subs: Map<string, Set<EventHandler>>;
  setStatus: (s: WsStatus, err?: string | null) => void;
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type EventHandler = (payload: any) => void;

export const useConnStore = create<ConnState>(() => ({
  status: "disconnected",
  lastError: null,
  _subs: new Map(),
  setStatus: (status, lastError = null) => useConnStore.setState({ status, lastError }),
}));

// eslint-disable-next-line @typescript-eslint/no-explicit-any
export function subscribeEvent(type: string, handler: EventHandler): () => void {
  const s = useConnStore.getState();
  let set = s._subs.get(type);
  if (!set) {
    set = new Set();
    s._subs.set(type, set);
  }
  set.add(handler);
  return () => {
    const cur = useConnStore.getState()._subs.get(type);
    cur?.delete(handler);
  };
}

/** 桥接基址：生产（webview 同源托管）用相对路径；dev（vite 5173）指向本地桥接端口 */
const BRIDGE_ORIGIN = import.meta.env.DEV
  ? ((import.meta.env.VITE_BRIDGE_URL as string | undefined) ?? "http://127.0.0.1:8765")
  : "";

let _token = "";
let _es: EventSource | null = null;
let _closed = true;              // 未连接
let _reconnectDelay = 1000;
let _reconnectTimer: ReturnType<typeof setTimeout> | null = null;

/** 读 token：生产由 /api/token 注入；dev 用 VITE_BRIDGE_TOKEN 或手动输入 */
function getDevToken(): string {
  try {
    const fromEnv = import.meta.env.VITE_BRIDGE_TOKEN as string | undefined;
    if (fromEnv) return fromEnv;
    return localStorage.getItem("daybreak.token") ?? "";
  } catch {
    return "";
  }
}

interface BridgeOpts {
  host?: string;
  port?: number;
  token?: string;
}

function apiUrl(path: string): string {
  return `${BRIDGE_ORIGIN}${path}`;
}

/** 是否已连上（SSE 处于 OPEN 且拿到过 token） */
function isOnline(): boolean {
  return !!_es && _es.readyState === EventSource.OPEN;
}

const WAIT_CONNECT_MS = 15000;

/**
 * 等待桥接上线（status → online 且 SSE OPEN）。
 * 已就绪立即 resolve；否则订阅状态变化，直到上线或超时。
 * 保留此语义：面板挂载时桥接可能尚未就绪（旧版 WS 时序竞态的经验）。
 */
function waitForOnline(timeoutMs: number = WAIT_CONNECT_MS): Promise<void> {
  return new Promise((resolve, reject) => {
    if (isOnline()) { resolve(); return; }
    let done = false;
    let unsub: (() => void) | undefined;
    const finish = (ok: boolean, msg?: string) => {
      if (done) return;
      done = true;
      clearTimeout(timer);
      unsub?.();
      if (ok) resolve(); else reject(new Error(msg ?? "bridge not connected"));
    };
    const timer = setTimeout(() => finish(false, "bridge not connected"), timeoutMs);
    unsub = useConnStore.subscribe((state, prev) => {
      if (state.status === "online" && prev.status !== "online") {
        setTimeout(() => finish(isOnline()), 0);
      }
    });
    if (useConnStore.getState().status === "online") {
      setTimeout(() => finish(isOnline()), 0);
    }
  });
}

/**
 * 发送命令并等待 ack/err（Promise 封装）。桥接未就绪时先等待上线再发送。
 * timeoutMs：每次请求的超时（默认 15s；长命令由调用方传更大值）。
 * 注意：window.move 这类高频命令每帧一次请求 —— fetch 走同源 keep-alive 连接复用，
 * 且调用方已有「至多一笔在途」背压，不会打爆连接池。
 */
export async function sendCommand(
  type: string,
  payload: Record<string, unknown> = {},
  timeoutMs: number = 15000,
): Promise<Record<string, unknown>> {
  await waitForOnline();
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), Math.max(1000, timeoutMs));
  try {
    const resp = await fetch(apiUrl("/api/rpc"), {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-Bridge-Token": _token },
      body: JSON.stringify({ v: 1, id: crypto.randomUUID(), type, payload }),
      signal: ctrl.signal,
    });
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const msg = (await resp.json()) as { type?: string; payload?: any };
    if (msg.type === "ack") return (msg.payload ?? {}) as Record<string, unknown>;
    const detail = msg?.payload?.message || msg?.payload?.code || msg.type || `HTTP ${resp.status}`;
    throw new Error(String(detail));
  } catch (e) {
    if ((e as Error).name === "AbortError") throw new Error(`cmd ${type} timeout`);
    throw e;
  } finally {
    clearTimeout(timer);
  }
}

/** 建立事件流（SSE 自带断线重连；这里只负责首次握手与状态同步） */
function openEvents(): void {
  closeEvents();
  const url = `${apiUrl("/api/events")}?token=${encodeURIComponent(_token)}`;
  const es = new EventSource(url);
  _es = es;

  es.onopen = () => {
    _reconnectDelay = 1000;
    useConnStore.setState({ status: "online", lastError: null });
  };

  es.onmessage = (ev) => {
    try {
      const msg = JSON.parse(ev.data as string) as { type?: string; payload?: unknown };
      if (msg.type) {
        const handlers = useConnStore.getState()._subs.get(msg.type);
        handlers?.forEach((h) => {
          try { h(msg.payload ?? {}); } catch { /* handler 异常不影响其它 */ }
        });
      }
    } catch {
      /* ignore malformed */
    }
  };

  es.onerror = () => {
    // EventSource 会自行重连；这里只把状态打回 reconnecting（UI 角标提示）
    if (_closed) return;
    useConnStore.setState({ status: "reconnecting" });
    // 浏览器在 4xx/网络彻底不可用时会停止自动重连 → 用退避定时器兜底重启
    if (es.readyState === EventSource.CLOSED) {
      closeEvents();
      if (_reconnectTimer) clearTimeout(_reconnectTimer);
      _reconnectTimer = setTimeout(() => {
        if (_closed) return;
        _reconnectDelay = Math.min(_reconnectDelay * 2, 30000);
        void connectBridge({ token: _token });
      }, _reconnectDelay);
    }
  };
}

function closeEvents(): void {
  if (_es) {
    _es.onopen = null;
    _es.onmessage = null;
    _es.onerror = null;
    _es.close();
    _es = null;
  }
}

export async function connectBridge(opts: BridgeOpts = {}): Promise<void> {
  const token = opts.token ?? getDevToken();
  _closed = false;
  useConnStore.setState({ status: "connecting" });

  if (!token) {
    useConnStore.setState({ status: "disconnected", lastError: "no token" });
    return;
  }
  _token = token;

  try {
    const r = await fetch(apiUrl("/api/ping"), { cache: "no-store" });
    if (!r.ok) throw new Error(`ping ${r.status}`);
  } catch (e) {
    useConnStore.setState({ status: "disconnected", lastError: `桥接服务不可达：${String(e)}` });
    return;
  }

  openEvents();
  if (token) localStorage.setItem("daybreak.token", token);
}

/**
 * 生产（webview 同源）/ dev：取 token。失败返回空串，由调用方决定提示。
 */
export async function fetchBridgeToken(): Promise<string> {
  try {
    const r = await fetch(apiUrl("/api/token"), { cache: "no-store" });
    if (!r.ok) return "";
    const j = (await r.json()) as { token?: string };
    return typeof j.token === "string" ? j.token : "";
  } catch {
    return "";
  }
}

export function disconnectBridge(): void {
  _closed = true;
  if (_reconnectTimer) { clearTimeout(_reconnectTimer); _reconnectTimer = null; }
  closeEvents();
  useConnStore.setState({ status: "disconnected" });
}
