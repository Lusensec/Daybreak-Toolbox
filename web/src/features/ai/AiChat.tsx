import { useEffect, useRef, useState } from "react";
import { Send, Loader2, Bot, Trash2 } from "lucide-react";
import { useAiStore } from "./store";
import { PROVIDERS, PROVIDER_LABELS } from "./providers";
import type { AiProviderInfo } from "./providers";
import { sendCommand, subscribeEvent } from "../../services/ws";
import "./AiChat.css";

/**
 * AI 对话（/ai）。按「分栏数量」渲染 1 栏或 2 分栏：
 *  - 动态 provider：ai.get_config 拉全量模型（含自定义，别名优先展示），失败回退内置 5 个
 *  - 分栏布局：统计 use_page!=0 的模型数。2 个 → 双栏（各自独立 session/历史）；
 *    1 个 → 单栏。每栏默认 provider = 对应激活模型，可在下拉内切换。
 *  - 输入：单栏 1 个输入行；双栏 1 个共享输入行（底部整行），同一问题并发发给所有分栏模型。
 *  - 每栏：选 provider → 输入 → ai.send 受理（ack + msg_id，session=分栏键）
 *  - ai.result 按 session 路由回对应分栏（整串，非逐 token；ok=false 红字提示）
 *  - 清空：清本栏前端消息 + 后端 ai.clear_session（历史按分栏隔离）
 *  - 订阅 ai.config_changed：改分栏数量/模型后立即重排布局（无需重启）
 */
export function AiChat() {
  const s = useAiStore;
  const panes = s((st) => st.panes);
  const [providers, setProviders] = useState<AiProviderInfo[]>([]);
  const [inputs, setInputs] = useState<Record<number, string>>({});
  const listRefs = useRef<Record<number, HTMLDivElement | null>>({});

  // 动态加载模型列表 + 推断分栏布局（按 use_page 激活数决定 1/2 栏）
  async function loadProviders() {
    try {
      const r = await sendCommand("ai.get_config", {});
      const models: string[] = (r.models ?? []) as string[];
      const cfg = (r.config ?? {}) as Record<string, { AI_alias?: string; use_page?: number }>;
      if (models.length) {
        const infos = models.map((name) => {
          const alias = (cfg[name]?.AI_alias ?? "").trim();
          return {
            name,
            label: alias ? `${alias}（${name}）` : PROVIDER_LABELS[name] ?? name,
            active: (cfg[name]?.use_page ?? 0) !== 0,
          };
        });
        setProviders(infos);
        // 分栏：>=2 个激活模型 → 双栏（各栏默认对应激活模型）；否则单栏
        const actives = infos.filter((p) => p.active).map((p) => p.name);
        const paneProviders =
          actives.length >= 2 ? [actives[0], actives[1]] : [actives[0] ?? models[0]];
        s.getState().syncLayout(paneProviders);
        return;
      }
    } catch {
      /* 断连或无配置：回退内置 */
    }
    setProviders(PROVIDERS.map((p) => ({ name: p, label: PROVIDER_LABELS[p] ?? p, active: true })));
    s.getState().syncLayout([PROVIDERS[0]]);
  }
  useEffect(() => {
    void loadProviders();
    const un = subscribeEvent("ai.config_changed", () => { void loadProviders(); });
    return () => { un(); };
  }, []);

  // 订阅 ai.result：按 session 路由到对应分栏
  useEffect(() => {
    const onResult = (p: any) => {
      const session = String(p?.session ?? "pane0");
      const i = parseInt(session.replace(/\D/g, ""), 10);
      if (Number.isNaN(i)) return;
      s.getState().pushAssistant(i, String(p?.text ?? ""), Boolean(p?.ok));
    };
    const un = subscribeEvent("ai.result", onResult);
    return () => { un(); };
  }, [s]);

  // 各分栏新消息贴底
  useEffect(() => {
    panes.forEach((_, i) => {
      const el = listRefs.current[i];
      if (el) el.scrollTo({ top: el.scrollHeight, behavior: "smooth" });
    });
  }, [panes]);

  const split = panes.length >= 2;
  const sharedText = inputs[0] ?? "";
  const anyBusy = panes.some((p) => p.busy);

  /** 本栏 provider 不在已加载动态模型里（极端竞态）→ 用启用模型或第一个。 */
  function resolvedProvider(name: string): string {
    return providers.length && !providers.some((p) => p.name === name)
      ? (providers.find((p) => p.active) ?? providers[0]).name
      : name;
  }

  /** 向分栏 i 发同一文本：用户消息 + 受理，结果由 ai.result（按 session）回写。 */
  function dispatch(i: number, text: string) {
    const st = s.getState();
    st.pushUser(i, text);
    st.markSending(i);
    sendCommand("ai.send", { session: st.paneSession(i), provider: resolvedProvider(st.panes[i]?.provider ?? ""), text })
      .catch((e) => st.pushAssistant(i, `AI 不可用：${e}`, false));
  }

  /** 单栏模式：输入行在栏内，本栏忙时禁用。 */
  function sendSingle() {
    const text = sharedText.trim();
    if (!text || panes[0].busy) return;
    setInputs((m) => ({ ...m, 0: "" }));
    dispatch(0, text);
  }

  /** 双栏模式：底部共享输入行，同一问题并发发给所有分栏的模型。 */
  function sendShared() {
    const text = sharedText.trim();
    if (!text || anyBusy) return;
    setInputs((m) => ({ ...m, 0: "" }));
    s.getState().panes.forEach((_, i) => dispatch(i, text));
  }

  async function clearPane(i: number) {
    const st = s.getState();
    st.clearPane(i);
    try {
      await sendCommand("ai.clear_session", { session: st.paneSession(i) });
    } catch { /* 断连忽略：前端已清 */ }
  }

  /** 分栏主体（头部 + 消息列表），双栏模式下共用，输入行在底部共享。 */
  function renderPane(i: number) {
    const pane = panes[i];
    return (
      <div key={i} className="ai-pane">
        <div className="ai-head">
          <span className="ai-pane__badge">分栏 {i + 1}</span>
          <label>
            <select
              value={pane.provider}
              onChange={(e) => s.getState().setPaneProvider(i, e.target.value)}
            >
              {providers.length ? (
                providers.map((p) => (
                  <option key={p.name} value={p.name}>
                    {p.label}{p.active ? " ●" : ""}
                  </option>
                ))
              ) : (
                <option value={pane.provider}>{PROVIDER_LABELS[pane.provider] ?? pane.provider}</option>
              )}
            </select>
          </label>
          <button className="ai-ghost" onClick={() => clearPane(i)} title="清空本栏会话">
            <Trash2 size={14} /> 清空
          </button>
        </div>

        <div className="ai-list" ref={(el) => { listRefs.current[i] = el; }}>
          {pane.messages.map((m, mi) => (
            <div key={mi} className={`ai-msg ai-msg-${m.role}`}>
              {m.role === "system" ? (
                <span className="ai-sys">{m.text}</span>
              ) : (
                <div className="ai-bubble">
                  {m.role === "assistant" ? (
                    <span className="ai-bot" title={PROVIDER_LABELS[pane.provider] ?? pane.provider}>
                      <Bot size={13} />
                    </span>
                  ) : null}
                  <span className={m.ok === false ? "ai-err-text" : "ai-text"}>{m.text}</span>
                </div>
              )}
            </div>
          ))}
          {pane.busy && (
            <div className="ai-msg ai-msg-assistant">
              <div className="ai-bubble">
                <span className="ai-bot"><Bot size={13} /></span>
                <span className="ai-waiting"><Loader2 size={13} className="spin" /> 正在思考…</span>
              </div>
            </div>
          )}
        </div>
      </div>
    );
  }

  const head = panes[0];

  return (
    <div className={"ai-panel" + (split ? " ai-panel--split" : "")}>
      {split ? (
        <>
          <div className="ai-split-body">
            {panes.map((_, i) => renderPane(i))}
          </div>
          {/* 共享输入行：同一问题并发发给两个分栏的模型 */}
          <div className="ai-input-row ai-input-row--shared">
            <input
              value={sharedText}
              placeholder="输入问题，Enter 发送（同一问题发给两栏模型）"
              onChange={(e) => setInputs((m) => ({ ...m, 0: e.target.value }))}
              onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); sendShared(); } }}
              disabled={anyBusy}
            />
            <button className="ai-send" onClick={sendShared} disabled={anyBusy || !sharedText.trim()}>
              <Send size={14} /> 发送
            </button>
          </div>
        </>
      ) : (
        <div className="ai-pane">
          <div className="ai-head">
            <label>
              <select
                value={head.provider}
                onChange={(e) => s.getState().setPaneProvider(0, e.target.value)}
              >
                {providers.length ? (
                  providers.map((p) => (
                    <option key={p.name} value={p.name}>
                      {p.label}{p.active ? " ●" : ""}
                    </option>
                  ))
                ) : (
                  <option value={head.provider}>{PROVIDER_LABELS[head.provider] ?? head.provider}</option>
                )}
              </select>
            </label>
            <button className="ai-ghost" onClick={() => clearPane(0)} title="清空本栏会话">
              <Trash2 size={14} /> 清空
            </button>
          </div>

          <div className="ai-list" ref={(el) => { listRefs.current[0] = el; }}>
            {head.messages.map((m, mi) => (
              <div key={mi} className={`ai-msg ai-msg-${m.role}`}>
                {m.role === "system" ? (
                  <span className="ai-sys">{m.text}</span>
                ) : (
                  <div className="ai-bubble">
                    {m.role === "assistant" ? (
                      <span className="ai-bot" title={PROVIDER_LABELS[head.provider] ?? head.provider}>
                        <Bot size={13} />
                      </span>
                    ) : null}
                    <span className={m.ok === false ? "ai-err-text" : "ai-text"}>{m.text}</span>
                  </div>
                )}
              </div>
            ))}
            {head.busy && (
              <div className="ai-msg ai-msg-assistant">
                <div className="ai-bubble">
                  <span className="ai-bot"><Bot size={13} /></span>
                  <span className="ai-waiting"><Loader2 size={13} className="spin" /> 正在思考…</span>
                </div>
              </div>
            )}
          </div>

          <div className="ai-input-row">
            <input
              value={sharedText}
              placeholder="输入问题，Enter 发送"
              onChange={(e) => setInputs((m) => ({ ...m, 0: e.target.value }))}
              onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); sendSingle(); } }}
              disabled={head.busy}
            />
            <button className="ai-send" onClick={sendSingle} disabled={head.busy || !sharedText.trim()}>
              <Send size={14} /> 发送
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
