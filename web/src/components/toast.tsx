import { create } from "zustand";
import { createPortal } from "react-dom";
import { CheckCircle2, XCircle, Info, X } from "lucide-react";
import "./toast.css";

type ToastKind = "ok" | "err" | "info";

interface ToastItem {
  id: number;
  kind: ToastKind;
  text: string;
}

interface ToastStore {
  items: ToastItem[];
  push: (kind: ToastKind, text: string) => void;
  remove: (id: number) => void;
}

let _seq = 0;
const TOAST_TTL = 3600; // 自动消失毫秒

export const useToastStore = create<ToastStore>((set) => ({
  items: [],
  push: (kind, text) => {
    const id = ++_seq;
    set((s) => ({ items: [...s.items.slice(-4), { id, kind, text }] })); // 最多堆叠 5 条
    setTimeout(() => set((s) => ({ items: s.items.filter((i) => i.id !== id) })), TOAST_TTL);
  },
  remove: (id) => set((s) => ({ items: s.items.filter((i) => i.id !== id) })),
}));

/** 便捷 hook：toast.ok("模型已添加") / toast.err(...) / toast.info(...) */
export function useToast() {
  const push = useToastStore((s) => s.push);
  return {
    ok: (t: string) => push("ok", t),
    err: (t: string) => push("err", t),
    info: (t: string) => push("info", t),
  };
}

/** 渲染在 body 右上角的全局提示框堆栈（z-index 高于模态框） */
export function ToastHost() {
  const items = useToastStore((s) => s.items);
  const remove = useToastStore((s) => s.remove);
  if (items.length === 0) return null;
  return createPortal(
    <div className="toast-host">
      {items.map((t) => {
        const Icon = t.kind === "ok" ? CheckCircle2 : t.kind === "err" ? XCircle : Info;
        return (
          <div key={t.id} className={`toast toast--${t.kind}`} role="status">
            <Icon size={15} />
            <span className="toast__text">{t.text}</span>
            <button className="toast__close" onClick={() => remove(t.id)} title="关闭">
              <X size={13} />
            </button>
          </div>
        );
      })}
    </div>,
    document.body,
  );
}
