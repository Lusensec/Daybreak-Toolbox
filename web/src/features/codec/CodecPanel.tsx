import { useState, useEffect } from "react";
import { Loader2 } from "lucide-react";
import {
  base64Encode, base64Decode,
  urlEncode, urlDecode,
  unicodeEncode, unicodeDecode,
  jsonFormat, md5,
} from "./codec";
import { sendCommand, subscribeEvent } from "../../services/ws";
import "./CodecPanel.css";

// 按钮集合（与 app.py create_encode_decode 一致）
interface Op {
  key: string;
  label: string;
  /** 纯前端同步 */
  run?: (text: string) => Promise<string> | string;
  /** 走 bridge（乱码修复） */
  bridge?: { type: string; field?: string };
}

const OPADES: Op[] = [
  { key: "b64e", label: "Base64编码", run: (t) => base64Encode(t) },
  { key: "b64d", label: "Base64解码", run: (t) => base64Decode(t) },
  { key: "urlE", label: "URL编码", run: (t) => urlEncode(t) },
  { key: "urlD", label: "URL解码", run: (t) => urlDecode(t) },
  { key: "uniE", label: "Unicode编码", run: (t) => unicodeEncode(t) },
  { key: "uniD", label: "Unicode解码", run: (t) => unicodeDecode(t) },
  { key: "reco", label: "乱码修复", bridge: { type: "codec.recover" } },
  { key: "json", label: "JSON格式化", run: (t) => jsonFormat(t) },
  { key: "md5", label: "MD5编码", run: async (t) => await md5(t) },
];

/**
 * 编解码面板（/codec）。纯函数前端化（Web 端），仅"乱码修复"走 bridge
 *（外部 ASP 服务，1:1 复刻 encryption.utf8_decode）。
 * 输入/输出双框；点击功能按钮把结果写进输出框，出错写错误提示。
 */
export function CodecPanel() {
  const [input, setInput] = useState("");
  const [output, setOutput] = useState("");
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);

  // 乱码修复是「受理即 ack、结果经 codec.recover 广播事件（worker 线程）推回」，
  // 必须在事件里回填输出，ack 本身不含 text（仅 {accepted}）——这是之前输出永远空的根因。
  useEffect(() => {
    const un = subscribeEvent("codec.recover", (p: Record<string, unknown>) => {
      const text = String(p?.text ?? "");
      if (text.startsWith("乱码修复出错")) {
        setErr(text.replace("乱码修复出错", "").trim() || "乱码修复失败");
        setOutput("");
      } else {
        setOutput(text);
        setErr("");
      }
      setBusy(false);
    });
    return () => { un(); };
  }, []);

  async function apply(op: Op) {
    const text = input.trim();
    setErr("");
    if (!text) {
      setOutput("");
      return;
    }
    if (op.bridge) {
      setBusy(true);
      setOutput("");
      try {
        await sendCommand(op.bridge.type, { text }); // 受理即返回，结果等 codec.recover 事件
      } catch (e) {
        setErr(`乱码修复出错：${e}`);
        setBusy(false);
      }
      return;
    }
    try {
      const res = await op.run!(text);
      setOutput(String(res));
    } catch (e) {
      setErr(`解码/处理出错：${e}`);
    }
  }

  return (
    <div className="codec-panel">
      <div className="codec-btns">
        {OPADES.map((op) => (
          <button
            key={op.key}
            className="codec-btn"
            disabled={busy}
            onClick={() => apply(op)}
          >
            {op.label}
          </button>
        ))}
      </div>

      <div className="codec-io">
        <div className="codec-col">
          <div className="codec-col-label">输入：</div>
          <textarea
            className="codec-box"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="粘贴待编码 / 解码的文本"
            spellCheck={false}
          />
        </div>
        <div className="codec-col">
          <div className="codec-col-label">输出：</div>
          <textarea
            className="codec-box"
            value={output}
            readOnly
            placeholder="结果"
            spellCheck={false}
          />
        </div>
      </div>

      {busy && <div className="codec-status"><Loader2 size={13} className="spin" /> 乱码修复中（走服务端）…</div>}
      {err && <div className="codec-status err">{err}</div>}
    </div>
  );
}
