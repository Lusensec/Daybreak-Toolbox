import { useEffect, useRef } from "react";
import { Languages, Loader2 } from "lucide-react";
import { useTranslateStore } from "./store";
import { sendCommand, subscribeEvent } from "../../services/ws";
import "./TranslatePanel.css";

/**
 * 汉英翻译面板（/translate）。
 *  - 操作行（翻译方向 + 翻译按钮）在上方
 *  - 输入/结果 左右双栏（同编解码布局）：左输入 textarea、右输出
 *  - 翻译走 bridge：sendCommand("translate.run") 受理，
 *    结果经 translate.result / translate.error 事件回写
 *  - 1:1 复刻 app.py：凭证缺失 / 出错时输出区显示后端返回的提示文案
 */
export function TranslatePanel() {
  const s = useTranslateStore;
  const input = s((st) => st.input);
  const output = s((st) => st.output);
  const busy = s((st) => st.busy);
  const pair = s((st) => st.pair);
  const reqId = useRef(0);

  // 订阅翻译结果 / 错误事件
  useEffect(() => {
    const onResult = (p: any) => {
      reqId.current += 1;
      s.getState().setOutput(String(p.text ?? ""));
      s.getState().setBusy(false);
    };
    const onErr = (p: any) => {
      s.getState().setOutput(String(p.message ?? "翻译出错"));
      s.getState().setBusy(false);
    };
    const un1 = subscribeEvent("translate.result", onResult);
    const un2 = subscribeEvent("translate.error", onErr);
    return () => {
      un1();
      un2();
    };
  }, [s]);

  async function doTranslate() {
    const text = s.getState().input.trim();
    if (!text) return;
    const [from_lang, to_lang] = s.getState().pair;
    const id = `t-${Date.now()}`;
    s.getState().setBusy(true);
    s.getState().setOutput("正在翻译…");
    try {
      await sendCommand("translate.run", { req_id: id, text, from_lang, to_lang });
      // 结果由事件回写；ack 仅代表受理
    } catch (e) {
      s.getState().setOutput(`翻译不可用：${e}`);
      s.getState().setBusy(false);
    }
  }

  const onKey = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    // Shift+Enter 触发（与旧版提示语一致）
    if (e.key === "Enter" && e.shiftKey) {
      e.preventDefault();
      doTranslate();
    }
  };

  const dirLabel =
    pair[0] === "en" ? "翻译方向: 英文 -> 中文" : "翻译方向: 中文 -> 英文";

  return (
    <div className="translate-panel">
      {/* 操作行：提示靠左，按钮靠右 */}
      <div className="translate-head">
        <span className="translate-note">
          输入框 Shift+Enter 发送；默认按首字符判断方向，未配置百度凭证时输出友好提示。
        </span>
        <button
          className="tp-btn ghost"
          onClick={() => s.getState().togglePair()}
          title={dirLabel}
        >
          <Languages size={14} /> {dirLabel}
        </button>
        <button
          className="tp-btn primary"
          onClick={doTranslate}
          disabled={busy || !input.trim()}
        >
          {busy ? <Loader2 size={14} className="spin" /> : null} 翻译
        </button>
      </div>

      {/* 左右双栏：输入 | 结果（同编解码布局） */}
      <div className="translate-io">
        <div className="translate-col">
          <div className="translate-col-label">输入：</div>
          <textarea
            className="translate-box"
            value={input}
            placeholder="粘贴待翻译的文本（可多行）"
            onChange={(e) => s.getState().setInput(e.target.value)}
            onKeyDown={onKey}
            spellCheck={false}
          />
        </div>
        <div className="translate-col">
          <div className="translate-col-label">翻译结果：</div>
          <textarea
            className="translate-box translate-box--ro"
            value={output}
            readOnly
            placeholder="结果"
            spellCheck={false}
          />
        </div>
      </div>
    </div>
  );
}
