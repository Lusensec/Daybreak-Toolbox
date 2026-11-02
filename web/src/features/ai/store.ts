import { create } from "zustand";

/** 一条聊天消息。 */
export interface ChatMsg {
  role: "user" | "assistant" | "system";
  text: string;
  ok?: boolean;
}

/** 单个分栏（独立会话 + 独立消息流 + 独立 provider + 独立历史）。 */
export interface PaneState {
  provider: string;
  messages: ChatMsg[];
  busy: boolean;
}

const SYS = "破晓·工具箱 AI 对话 —— 选择一个模型开始提问。";

function freshPane(provider: string): PaneState {
  return { provider, messages: [{ role: "system", text: SYS }], busy: false };
}

interface AiState {
  /** 分栏数组：1 栏 = 1 项，2 栏 = 2 项（各自独立 session）。 */
  panes: PaneState[];

  /** 按后端 use_page 推导的「分栏数 + 默认 provider」对齐本 store。
   *  新增的分栏用对应 provider；已存在的分栏保留用户已选的 provider。
   *  providers.length===1 → 单栏；===2 → 双栏。 */
  syncLayout: (providers: string[]) => void;
  setPaneProvider: (i: number, p: string) => void;
  pushUser: (i: number, text: string) => void;
  markSending: (i: number) => void;
  pushAssistant: (i: number, text: string, ok: boolean) => void;
  clearPane: (i: number) => void;
  /** 分栏 → 后端 session 键（历史按此隔离）。 */
  paneSession: (i: number) => string;
}

export const useAiStore = create<AiState>((set) => ({
  panes: [freshPane("kimi_ai")],

  syncLayout: (providers) =>
    set((s) => {
      const n = Math.max(1, providers.length);
      const next = s.panes.slice(0, n);
      for (let i = next.length; i < n; i++) next.push(freshPane(providers[i] ?? providers[0] ?? ""));
      // 分栏数缩减时截断；保留已存在分栏的 provider/消息
      return { panes: next };
    }),

  setPaneProvider: (i, p) =>
    set((s) => ({ panes: s.panes.map((pane, k) => (k === i ? { ...pane, provider: p } : pane)) })),

  pushUser: (i, text) =>
    set((s) => ({
      panes: s.panes.map((pane, k) =>
        k === i ? { ...pane, messages: [...pane.messages, { role: "user", text }] } : pane),
    })),

  markSending: (i) =>
    set((s) => ({
      panes: s.panes.map((pane, k) => (k === i ? { ...pane, busy: true } : pane)),
    })),

  pushAssistant: (i, text, ok) =>
    set((s) => ({
      panes: s.panes.map((pane, k) =>
        k === i
          ? { ...pane, busy: false, messages: [...pane.messages, { role: "assistant", text, ok }] }
          : pane),
    })),

  clearPane: (i) =>
    set((s) => ({
      panes: s.panes.map((pane, k) =>
        k === i ? { ...pane, busy: false, messages: [{ role: "system", text: "新会话已开启。" }] } : pane),
    })),

  paneSession: (i) => `pane${i}`,
}));
