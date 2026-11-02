import { useEffect, useState } from "react";
import { useToastStore } from "../../components/toast";
import { useShortcutsStore } from "./store";
import { effectiveCombo, eventCombo, defaultCombo } from "./shortcuts";

/**
 * 快捷键录入控件：
 *  - 显示生效组合（已存值优先，否则默认，均无则「未设置」）；默认值带「默认」小标
 *  - 点击 → 进入录键态：按下 含 Ctrl 的组合即写入（Esc 取消）；非法组合给出提示
 *  - 「✕」清除：写入空串 = 显式停用（对默认槽即关闭该默认快捷键）
 *  - conflict：与其它槽位撞了同一组合 → 红色 ⚠
 *  - toolCombo：工具槽的按序默认组合（Ctrl+Alt+N）；录键覆盖即「自定义」
 */
export function KeyCapture({ slotKey, dynMenus, fixMenus, conflict, toolCombo }: {
  slotKey: string;
  dynMenus: string[];
  fixMenus: string[];
  conflict?: boolean;
  toolCombo?: string;
}) {
  const map = useShortcutsStore((s) => s.map);
  const setSlot = useShortcutsStore((s) => s.setSlot);
  const [recording, setRecording] = useState(false);
  const [hint, setHint] = useState("");

  const saved = Object.prototype.hasOwnProperty.call(map, slotKey) ? map[slotKey] ?? "" : null;
  const value = saved !== null
    ? saved
    : toolCombo ?? effectiveCombo(map, slotKey, dynMenus, fixMenus);
  const isDefault = saved === null && !!value;

  useEffect(() => {
    if (!recording) return;
    const onKey = (e: KeyboardEvent) => {
      e.preventDefault();
      e.stopPropagation();
      if (e.key === "Escape") { setRecording(false); setHint(""); return; }
      const combo = eventCombo(e);
      if (!combo) {
        setHint("需含 Ctrl（如 Ctrl+K / Ctrl+Alt+Shift+P / Ctrl+1）");
        return;
      }
      setRecording(false);
      setHint("");
      void setSlot(slotKey, combo).catch((err) => {
        useToastStore.getState().push("err", String(err instanceof Error ? err.message : err));
      });
    };
    document.addEventListener("keydown", onKey, true);
    return () => document.removeEventListener("keydown", onKey, true);
  }, [recording, slotKey, setSlot]);

  return (
    <div className="key-capture">
      <button
        type="button"
        className={
          "key-capture__combo" +
          (value ? "" : " is-empty") +
          (recording ? " is-recording" : "") +
          (conflict ? " is-conflict" : "")
        }
        title={recording ? "按下组合键（Esc 取消）" : "点击重新录制组合键"}
        onClick={() => { setRecording(true); setHint(""); }}
      >
        {recording ? "按下组合键…" : (value || "未设置")}
      </button>
      {isDefault && value ? <em className="key-capture__default">默认</em> : null}
      {saved === "" ? <em className="key-capture__off">已停用</em> : null}
      {conflict ? <em className="key-capture__conflict">⚠ 冲突</em> : null}
      {value ? (
        <button
          type="button"
          className="key-capture__clear"
          title="停用该快捷键"
          onClick={() => {
            setHint("");
            void setSlot(slotKey, "").catch((err) => {
              useToastStore.getState().push("err", String(err instanceof Error ? err.message : err));
            });
          }}
        >✕</button>
      ) : null}
      {saved === "" ? (
        <button
          type="button"
          className="key-capture__restore"
          title="恢复默认组合（工具槽恢复按序默认 Ctrl+Alt+N）"
          onClick={() => {
            setHint("");
            void setSlot(slotKey, defaultCombo(slotKey, dynMenus, fixMenus) ?? toolCombo ?? "").catch((err) => {
              useToastStore.getState().push("err", String(err instanceof Error ? err.message : err));
            });
          }}
        >恢复</button>
      ) : null}
      {hint ? <span className="key-capture__hint">{hint}</span> : null}
    </div>
  );
}
