import { create } from "zustand";

/**
 * 菜单栏「脱离为子窗口」状态（纯 UI 状态，不写 config：刷新页面全部收回栏内）。
 *
 * detached: 菜单名 → 子窗口 {x, y, w, h}；zOrder: 尾部 = 最上层（置顶焦点）。
 * 同一菜单同时只允许一个子窗口（open 幂等：已脱离则仅移动/置顶）。
 * AI 对话/终端管理/临时笔记 等全局单例状态在多窗间共享（用户已确认允许）。
 */
interface DetachState {
  detached: Record<string, { x: number; y: number; w: number; h: number }>;
  zOrder: string[];
  /** 拖拽中「插入位」高亮的目标菜单名（被悬停的那一个），null = 无 */
  hoverTarget: string | null;
  open: (name: string, x: number, y: number) => void;
  close: (name: string) => void;
  move: (name: string, x: number, y: number) => void;
  /** 拉伸（右下角把手）：w/h 钳制在 [FLOAT_MIN, min(FLOAT_MAX, 视口)]，x/y 随新尺寸收拢 */
  resize: (name: string, w: number, h: number) => void;
  focus: (name: string) => void;
  setHoverTarget: (name: string | null) => void;
  /** 1000+ 层位：zOrder 中越靠后 z 越高 */
  zIndexOf: (name: string) => number;
}

/** 子窗口默认尺寸与拉伸上下限 */
export const FLOAT_W = 760;
export const FLOAT_H = 480;
export const FLOAT_MIN = { w: 420, h: 300 };
export const FLOAT_MAX = { w: 1400, h: 900 };

/** 把子窗口左上角钳制在视口内（贴边时往里收，保证至少 8px 可见边距） */
export function clampFloatPos(x: number, y: number, w = FLOAT_W, h = FLOAT_H): { x: number; y: number } {
  const vw = Math.min(w, window.innerWidth - 16);
  const vh = Math.min(h, window.innerHeight - 16);
  const maxX = Math.max(8, window.innerWidth - vw - 8);
  const maxY = Math.max(8, window.innerHeight - vh - 8);
  return {
    x: Math.min(maxX, Math.max(8, x)),
    y: Math.min(maxY, Math.max(8, y)),
  };
}

export const useDetachStore = create<DetachState>((set, get) => ({
  detached: {},
  zOrder: [],
  hoverTarget: null,

  open(name, x, y) {
    const s = get();
    // 默认尺寸钳制到视口（小屏幕不超框）
    const w = Math.min(FLOAT_W, window.innerWidth - 16);
    const h = Math.min(FLOAT_H, window.innerHeight - 16);
    const p = clampFloatPos(x, y, w, h);
    set({
      detached: { ...s.detached, [name]: { x: p.x, y: p.y, w, h } },
      zOrder: [...s.zOrder.filter((n) => n !== name), name],
    });
  },

  close(name) {
    const s = get();
    const detached = { ...s.detached };
    delete detached[name];
    set({ detached, zOrder: s.zOrder.filter((n) => n !== name) });
  },

  move(name, x, y) {
    const s = get();
    const p = s.detached[name];
    if (!p) return;
    const c = clampFloatPos(x, y, p.w, p.h);
    set({ detached: { ...s.detached, [name]: { ...p, x: c.x, y: c.y } } });
  },

  resize(name, w, h) {
    const s = get();
    const p = s.detached[name];
    if (!p) return;
    // w/h 钳制：min 固定；max = 配置上限 与 视口（16px 边距）取小
    const cw = Math.max(FLOAT_MIN.w, Math.min(Math.min(FLOAT_MAX.w, window.innerWidth - 16), w));
    const ch = Math.max(FLOAT_MIN.h, Math.min(Math.min(FLOAT_MAX.h, window.innerHeight - 16), h));
    const c = clampFloatPos(p.x, p.y, cw, ch); // 变大时左上角随新尺寸收拢（右下角向外长）
    set({ detached: { ...s.detached, [name]: { x: c.x, y: c.y, w: cw, h: ch } } });
  },

  focus(name) {
    const s = get();
    if (!s.zOrder.includes(name) || s.zOrder[s.zOrder.length - 1] === name) return;
    set({ zOrder: [...s.zOrder.filter((n) => n !== name), name] });
  },

  setHoverTarget(name) {
    if (get().hoverTarget !== name) set({ hoverTarget: name });
  },

  zIndexOf(name) {
    const i = get().zOrder.indexOf(name);
    return 1000 + Math.max(0, i);
  },
}));
