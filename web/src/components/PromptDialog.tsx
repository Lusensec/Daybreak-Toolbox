import { useEffect, useRef, useState } from "react";
import { create } from "zustand";
import { X } from "lucide-react";
import "./PromptDialog.css";

/**
 * 全局重命名/输入对话框（替代 window.prompt）：
 *  - 由任意上下文（顶栏右键菜单 / 设置页列表行 / 子窗口导航行）调用 promptOpen(title, initial)
 *    → 返回 Promise<string | null>（null = 取消 / 空名 / 与原值相同；AppShell 顶层 Host 渲染）
 *  - 交互：输入框自动聚焦并全选；Enter 确定、Esc 取消；遮罩点击取消
 *  - 防叠框：已有对话框打开时再次调用立即返回 null
 */
interface PromptState {
  title: string;
  initial: string;
  /** 结算函数（打开时写入；close 时调用一次） */
  resolve: ((v: string | null) => void) | null;
  openDialog: (title: string, initial: string) => Promise<string | null>;
  close: (value: string | null) => void;
}

export const usePromptStore = create<PromptState>((set, get) => ({
  title: "",
  initial: "",
  resolve: null,

  openDialog(title, initial) {
    // 已有对话框 → 不叠框，直接按取消处理
    if (get().resolve) return Promise.resolve(null);
    return new Promise<string | null>((resolveFn) => {
      set({ title, initial, resolve: resolveFn });
    });
  },

  close(value) {
    const r = get().resolve;
    if (!r) return;
    set({ resolve: null });
    r(value);
  },
}));

/** 便捷调用：打开对话框，resolve 新名称（null = 取消/无效输入） */
export function promptOpen(title: string, initial: string): Promise<string | null> {
  return usePromptStore.getState().openDialog(title, initial);
}

/** AppShell 顶层挂载（与 ToastHost 同级）：无打开态时渲染 null */
export function PromptDialogHost() {
  const title = usePromptStore((s) => s.title);
  const initial = usePromptStore((s) => s.initial);
  const resolve = usePromptStore((s) => s.resolve);
  const close = usePromptStore((s) => s.close);
  const [value, setValue] = useState(initial);
  const inputRef = useRef<HTMLInputElement>(null);

  // 每次打开（initial 变化）重置输入值
  useEffect(() => { setValue(initial); }, [initial]);

  // 自动聚焦 + 全选
  useEffect(() => {
    if (resolve && inputRef.current) {
      inputRef.current.focus();
      inputRef.current.select();
    }
  }, [resolve, initial]);

  // Esc 取消（Enter 在 input 上处理）
  useEffect(() => {
    if (!resolve) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") close(null); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [resolve, close]);

  if (!resolve) return null;

  function submit() {
    const v = value.trim();
    // 空串 / 与原值相同 → 等同取消（与原生 prompt 行为一致）
    close(v && v !== initial ? v : null);
  }

  return (
    <div className="prompt-mask" onMouseDown={(e) => { if (e.target === e.currentTarget) close(null); }}>
      <div className="prompt-dialog" role="dialog" aria-modal="true">
        <div className="prompt-dialog__title">
          {title}
          <button className="prompt-dialog__close" title="取消" onClick={() => close(null)}>
            <X size={14} />
          </button>
        </div>
        <input
          ref={inputRef}
          className="prompt-dialog__input"
          value={value}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter") submit(); }}
          spellCheck={false}
        />
        <div className="prompt-dialog__row">
          <span className="prompt-dialog__hint">勿用空格与特殊字符；Enter 确定 / Esc 取消</span>
          <div className="prompt-dialog__btns">
            <button className="prompt-dialog__btn primary" onClick={submit}>确定</button>
            <button className="prompt-dialog__btn" onClick={() => close(null)}>取消</button>
          </div>
        </div>
      </div>
    </div>
  );
}
