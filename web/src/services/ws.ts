/**
 * 破晓·工具箱 —— 前端最小 WS 客户端
 *
 * 职责（Phase 0 骨架）：
 *  - 连接 ws://<host>:<port>/ws?token=***
 *  - 断线指数退避重连（1/2/4/8/16/30s 封顶）
 *  - 15s 心跳（ping）
 *  - 事件分发到 zustand connection store
 *
 * 事件信封与 bridge/ws.py 对齐：
 *   请求 {"v":1,"id","type","payload"} → 响应 {"v":1,"id","type":"ack|err","payload"}
 *   事件 {"v":1,"type","payload"}
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

/** 读 token：生产由 entry.py 注入 localStorage；dev 用 VITE_BRIDGE_TOKEN 或手动 */
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

let _ws: WebSocket | null = null;
let _closed = false;
let _reconnectDelay = 1000;
let _hbTimer: ReturnType<typeof setInterval> | null = null;

const WAIT_CONNECT_MS = 15000;

function isWsReady(): boolean {
  return !!_ws && _ws.readyState === WebSocket.OPEN;
}

/**
 * 等待桥接 WS 上线（status → online 且 ws OPEN）。
 * 已就绪立即 resolve；否则订阅状态变化，直到上线或超时（超时 reject "ws not connected"）。
 * 用于消除「面板挂载时 WS 尚未 OPEN」的时序竞态（旧版 sendCommand 直接拒绝导致 加载失败）。
 */
function waitForOnline(timeoutMs: number = WAIT_CONNECT_MS): Promise<void> {
  return new Promise((resolve, reject) => {
    if (isWsReady()) { resolve(); return; }
    let done = false;
    let unsub: (() => void) | undefined;
    const finish = (ok: boolean, msg?: string) => {
      if (done) return;
      done = true;
      clearTimeout(timer);
      unsub?.();
      if (ok) resolve(); else reject(new Error(msg ?? "ws not connected"));
    };
    const timer = setTimeout(() => finish(false, "ws not connected"), timeoutMs);
    unsub = useConnStore.subscribe((state, prev) => {
      if (state.status === "online" && prev.status !== "online") {
        // 留一个宏任务让 ws 真正 OPEN
        setTimeout(() => finish(isWsReady()), 0);
      }
    });
    // 若此刻已 online（但 ws 尚在 settle），也立即收一次
    if (useConnStore.getState().status === "online") {
      setTimeout(() => finish(isWsReady()), 0);
    }
  });
}

/** 发送命令并等待 ack/err（Promise 封装）。WS 未就绪时会先等待桥接上线再发送。 */
export async function sendCommand(type: string, payload: Record<string, unknown> = {}): Promise<Record<string, unknown>> {
  await waitForOnline();
  return new Promise((resolve, reject) => {
    if (!isWsReady()) {
      reject(new Error("ws not connected"));
      return;
    }
    const id = crypto.randomUUID();
    const timer = setTimeout(() => reject(new Error(`cmd ${type} timeout`)), 15000);
    const onMsg = (ev: MessageEvent) => {
      try {
        const msg = JSON.parse(ev.data as string) as { id?: string; type?: string; payload?: unknown };
        if (msg.id === id) {
          clearTimeout(timer);
          _ws?.removeEventListener("message", onMsg);
          if (msg.type === "ack") resolve((msg.payload ?? {}) as Record<string, unknown>);
          else reject(new Error(String((msg.payload as { message?: string })?.message ?? msg.type)));
        }
      } catch {
        /* 非本 id 的消息，忽略 */
      }
    };
    _ws!.addEventListener("message", onMsg);
    _ws!.send(JSON.stringify({ v: 1, id, type, payload }));
  });
}

export async function connectBridge(opts: BridgeOpts = {}): Promise<void> {
  const host = opts.host ?? "127.0.0.1";
  const port = opts.port ?? 8765;
  const token = opts.token ?? getDevToken();
  _closed = false;
  const url = `ws://${host}:${port}/ws?token=${token}`;
  useConnStore.setState((s) => ({ ...s, status: token ? "connecting" : "disconnected" }));

  if (!token) {
    useConnStore.setState({ status: "disconnected", lastError: "no token (set VITE_BRIDGE_TOKEN or localStorage.daybreak.token)" });
    return;
  }

  _ws = new WebSocket(url);

  _ws.onopen = () => {
    _reconnectDelay = 1000;
    useConnStore.setState({ status: "online", lastError: null });
    _startHeartbeat();
  };

  _ws.onmessage = (ev) => {
    // 事件分发（无 id 的为服务端事件）
    try {
      const msg = JSON.parse(ev.data as string) as { type?: string; payload?: unknown; id?: string };
      if (msg.type && msg.id === undefined) {
        const handlers = useConnStore.getState()._subs.get(msg.type);
        handlers?.forEach((h) => {
          try { h(msg.payload ?? {}); } catch { /* handler 异常不影响其它 */ }
        });
      }
    } catch {
      /* ignore malformed */
    }
  };

  _ws.onclose = () => {
    _stopHeartbeat();
    if (_closed) return;
    useConnStore.setState({ status: "reconnecting" });
    setTimeout(() => connectBridge(opts), _reconnectDelay);
    _reconnectDelay = Math.min(_reconnectDelay * 2, 30000);
  };

  _ws.onerror = () => {
    _ws?.close();
  };
}

/**
 * 生产/bridge 自托管模式：从同源 /api/token 取 token（bridge/main.py 提供）。
 * 失败返回空串，由调用方决定提示。
 */
export async function fetchBridgeToken(): Promise<string> {
  try {
    const r = await fetch("/api/token");
    if (!r.ok) return "";
    const j = (await r.json()) as { token?: string };
    return typeof j.token === "string" ? j.token : "";
  } catch {
    return "";
  }
}

export function disconnectBridge(): void {
  _closed = true;
  _stopHeartbeat();
  _ws?.close();
  _ws = null;
  useConnStore.setState({ status: "disconnected" });
}

function _startHeartbeat() {
  _stopHeartbeat();
  _hbTimer = setInterval(() => {
    if (_ws?.readyState === WebSocket.OPEN) {
      _ws.send(JSON.stringify({ v: 1, id: crypto.randomUUID(), type: "ping", payload: {} }));
    }
  }, 15000);
}

function _stopHeartbeat() {
  if (_hbTimer) clearInterval(_hbTimer);
  _hbTimer = null;
}
