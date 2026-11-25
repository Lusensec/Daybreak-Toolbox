import { useEffect, useRef, useState } from "react";
import { Terminal, Trash2, RotateCcw, Minus, Plus, Loader2, Folder, Globe, Unplug } from "lucide-react";
import { sendCommand } from "../../services/ws";
import { useSshStore } from "../ssh/store";
import { SshHostSelect } from "../ssh/SshHostSelect";
import "./ShellPanel.css";

/** 输出条目（命令回显 / 结果 / 提示 / 错误） */
interface Line {
  kind: "cmd" | "out" | "err" | "info";
  text: string;
}

/** 长路径中段省略（保留盘符 + 尾部目录，尾部辨识度最高） */
function truncateMid(s: string, n = 44): string {
  if (s.length <= n) return s;
  const keep = Math.floor((n - 1) / 2);
  return s.slice(0, keep) + "…" + s.slice(s.length - keep);
}

const FS_KEY = "daybreak.shell.fs";
const FS_MIN = 10;
const FS_MAX = 28;
const SESSION = "local";
const MAX_COMPLETE = 8;

/** 终端类型显示名（option 文案） */
const SHELL_LABEL: Record<string, string> = {
  cmd: "cmd",
  powershell: "PowerShell",
  pwsh: "pwsh (Core)",
};

export function ShellPanel() {
  const [lines, setLines] = useState<Line[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [cwd, setCwd] = useState("");
  const [history, setHistory] = useState<string[]>([]);
  const [histIdx, setHistIdx] = useState(-1);
  const [fontSize, setFontSize] = useState<number>(() => {
    const v = Number(localStorage.getItem(FS_KEY));
    return Number.isFinite(v) && v >= FS_MIN && v <= FS_MAX ? v : 14;
  });
  // Tab 补全浮层
  const [sug, setSug] = useState<string[]>([]);
  const [sugIdx, setSugIdx] = useState(-1);
  // 终端类型（按系统探测：cmd / PowerShell / pwsh）
  const [shells, setShells] = useState<string[]>([]);
  const [shell, setShell] = useState("cmd");

  // SSH 远端模式：导航条选中主机即连接（store 驱动）→ 命令改在远端执行
  const activeAlias = useSshStore((s) => s.activeAlias);
  const hostInfo = useSshStore((s) => s.hosts.find((h) => h.alias === s.activeAlias));
  const selectSsh = useSshStore((s) => s.select);
  const remote = activeAlias !== null;
  const prevRemoteRef = useRef(false);

  const outRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  // 字号持久
  useEffect(() => {
    localStorage.setItem(FS_KEY, String(fontSize));
  }, [fontSize]);

  // 输出自动滚底
  useEffect(() => {
    const el = outRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [lines]);

  // 命令执行完毕（busy 释放、input 解除 disabled）后，把光标还回命令输入框；
  // 挂载时 busy=false 同一路径 → 进入终端管理默认光标就在输入行。
  // 注意：点击输出区**不**抢焦点（保留选择/复制命令结果的能力）。
  useEffect(() => {
    if (!busy) requestAnimationFrame(() => inputRef.current?.focus());
  }, [busy]);

  // 挂载：静默初始化（终端默认空白，干净利落）——
  //   pwd 只用于初始化工具栏的路径芯片（不再回显进输出区）；探测可用终端类型
  useEffect(() => {
    void sendCommand("shell.run", { session: SESSION, command: "pwd" })
      .then((r: Record<string, unknown>) => setCwd(String(r.cwd ?? "")))
      .catch(() => {});
    void sendCommand("shell.shells", { session: SESSION })
      .then((r: Record<string, unknown>) => {
        setShells((r.available ?? []) as string[]);
        setShell(String(r.current ?? "cmd"));
      })
      .catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // 本地 ⇄ 远端 模式切换提示（远端会话被断开时 ssh.closed 广播会把 activeAlias 清回 null）
  useEffect(() => {
    const isRemote = activeAlias !== null;
    if (prevRemoteRef.current && !isRemote) {
      setLines((l) => [...l, { kind: "info", text: "SSH 会话已断开，切回本地终端" }]);
    } else if (!prevRemoteRef.current && isRemote) {
      setLines((l) => [...l, { kind: "info", text: `已连接远端主机「${activeAlias}」（命令在远端执行）` }]);
    }
    prevRemoteRef.current = isRemote;
  }, [activeAlias]);

  async function run(cmd: string) {
    const command = cmd.trim();
    if (!command) return; // 空命令不回显（避免空块）
    setLines((l) => [...l, { kind: "cmd", text: command }]);
    setBusy(true);
    try {
      // 远端模式：命令经 bridge 常驻 SSH 会话在目标主机执行（响应与本地同款 {ok,output,exit,truncated}）
      // 长命令预算 90s：后端 cmd/ssh 单条最长 60s；PS 常驻超时后重试封顶 15s（全程 ≤ ~80s）
      // —— 默认 15s 前端超时会先于后端放弃 → 误报「cmd shell.run timeout」
      const r: Record<string, unknown> = remote
        ? await sendCommand("ssh.run", { alias: activeAlias, command, timeout: 60 }, 90000)
        : await sendCommand("shell.run", { session: SESSION, command }, 90000);
      const out = String(r.output ?? "");
      if (!remote && r.clear) {
        setLines([]); // 清屏：本地 exit / clear（旧版 exit 也是清屏而非退出）
      } else {
        if (out.trim()) setLines((l) => [...l, { kind: "out", text: out.replace(/\n+$/, "") }]);
        if (r.truncated) setLines((l) => [...l, { kind: "info", text: "…（输出过长，已截断为尾部）" }]);
        if (!r.ok) setLines((l) => [...l, { kind: "err", text: remote ? `（远端 exit ${String(r.exit)}）` : `（exit ${String(r.exit)}）` }]);
      }
      if (!remote) setCwd(String(r.cwd ?? ""));
    } catch (e) {
      setLines((l) => [...l, { kind: "err", text: remote ? `远端执行失败：${String(e instanceof Error ? e.message : e)}` : String(e instanceof Error ? e.message : e) }]);
      if (remote) setLines((l) => [...l, { kind: "info", text: "会话可能已断开：可在导航条 SSH 下拉框重新选择该主机" }]);
    } finally {
      setBusy(false);
      setInput("");
      setSug([]);
    }
  }

  function submit() {
    if (busy) return;
    if (input.trim()) {
      setHistory((h) => [...h, input]);
    }
    setHistIdx(-1);
    void run(input);
  }

  async function tabComplete() {
    if (busy || !input || remote) return; // Tab 补全基于本地文件系统，远端模式不适用
    const last = input.match(/[\w./\\_-]+$/)?.[0] ?? "";
    const r = await sendCommand("shell.complete", { session: SESSION, prefix: last });
    const items = (r.items ?? []) as string[];
    if (items.length === 0) {
      setSug([]);
      return;
    }
    setSug(items.slice(0, MAX_COMPLETE));
    setSugIdx(0);
  }

  function applySug(item: string) {
    setInput((cur) => cur.replace(/[\w./\\_-]+$/, item));
    setSug([]);
    setSugIdx(-1);
  }

  function onKey(e: React.KeyboardEvent<HTMLInputElement>) {
    // 补全浮层导航优先
    if (sug.length > 0 && (e.key === "ArrowDown" || e.key === "ArrowUp" || e.key === "Tab" || e.key === "Enter")) {
      e.preventDefault();
      if (e.key === "ArrowDown") { setSugIdx((i) => (i + 1) % sug.length); return; }
      if (e.key === "ArrowUp") { setSugIdx((i) => (i - 1 + sug.length) % sug.length); return; }
      applySug(sug[sugIdx] ?? sug[0]);
      return;
    }
    if (e.key === "Enter") {
      e.preventDefault();
      submit();
    } else if (e.key === "Tab") {
      e.preventDefault();
      void tabComplete();
    } else if (e.key === "Escape") {
      setSug([]); setSugIdx(-1);
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      // 命令历史：上翻
      if (history.length === 0) return;
      const ni = histIdx === -1 ? history.length - 1 : Math.max(0, histIdx - 1);
      setHistIdx(ni);
      setInput(history[ni]);
    } else if (e.key === "ArrowDown") {
      e.preventDefault();
      if (histIdx === -1) return;
      const ni = histIdx + 1;
      if (ni >= history.length) { setHistIdx(-1); setInput(""); }
      else { setHistIdx(ni); setInput(history[ni]); }
    }
  }

  function clearScreen() {
    setLines([]);
  }
  async function resetCwd() {
    const r = await sendCommand("shell.reset", { session: SESSION });
    setCwd(String(r.cwd ?? ""));
    setLines((l) => [...l, { kind: "info", text: `cwd 已重置为 ${r.cwd}` }]);
  }

  // 命令分块：遇 cmd 起一块，其后结果/提示/错误归入同一块（块间画分隔线）
  const blocks: { cmd: Line | null; out: Line[] }[] = [];
  for (const l of lines) {
    if (l.kind === "cmd") blocks.push({ cmd: l, out: [] });
    else if (blocks.length) blocks[blocks.length - 1].out.push(l);
    else blocks.push({ cmd: null, out: [l] });
  }

  return (
    <div className="shell-panel">
      <div className="shell-bar">
        <span className="shell-bar__title">
          {remote ? <Globe size={15} /> : <Terminal size={15} />}
          {remote ? `终端管理 · ${activeAlias}` : "终端管理"}
        </span>
        {remote ? (
          <span className="shell-bar__cwd shell-bar__cwd--remote" title={`${hostInfo?.username ?? ""}@${hostInfo?.host ?? ""}（SSH）`}>
            <Globe size={11} />
            <span className="shell-bar__cwd-text">
              {hostInfo ? `${hostInfo.username}@${hostInfo.host}` : activeAlias}
              {(hostInfo?.port ?? 22) !== 22 ? `:${hostInfo?.port}` : ""}
            </span>
            <button className="shell-ic shell-bar__disconnect" title="断开 SSH，回本地终端" onClick={() => { void selectSsh(null).catch(() => {}); }}>
              <Unplug size={13} />
            </button>
          </span>
        ) : (
          <span className="shell-bar__cwd" title={cwd}>
            <Folder size={11} />
            <span className="shell-bar__cwd-text">{truncateMid(cwd) || "…"}</span>
          </span>
        )}
        {/* SSH 主机下拉框：路径芯片与终端类型之间；选中即连接（远端/本地模式均可切换主机） */}
        <SshHostSelect />
        {!remote ? (
          <select
            className="shell-bar__shell"
            value={shell}
            title="当前终端类型（按系统可用项，影响非内置命令的执行方式）"
            onChange={(e) => {
              const s = e.target.value;
              setShell(s);
              void sendCommand("shell.set_shell", { session: SESSION, shell: s }).catch(() => {});
            }}
          >
            {(shells.length ? shells : ["cmd"]).map((s) => (
              <option key={s} value={s}>{SHELL_LABEL[s] ?? s}</option>
            ))}
          </select>
        ) : null}
        <div className="shell-bar__tools">
          <button className="shell-ic" title="缩小字号" onClick={() => setFontSize((f) => Math.max(FS_MIN, f - 1))}><Minus size={13} /></button>
          <span className="shell-bar__fs">{fontSize}px</span>
          <button className="shell-ic" title="放大字号" onClick={() => setFontSize((f) => Math.min(FS_MAX, f + 1))}><Plus size={13} /></button>
          <button className="shell-ic" title="清屏" onClick={clearScreen}><Trash2 size={13} /></button>
          {!remote ? (
            <button className="shell-ic" title="重置 cwd 到项目根" onClick={() => void resetCwd()}><RotateCcw size={13} /></button>
          ) : null}
        </div>
      </div>

      <div className="shell-body" style={{ fontSize }}>
        <div className="shell-out" ref={outRef}>
          {blocks.map((b, bi) => (
            <div key={bi} className="shell-block">
              {b.cmd ? (
                <div className="shell-line shell-line--cmd">
                  <span className="shell-line__sigil">❯</span>
                  {b.cmd.text || "\u00A0"}
                </div>
              ) : null}
              {b.out.map((o, oi) => (
                <div key={oi} className={`shell-line shell-line--${o.kind}`}>{o.text || "\u00A0"}</div>
              ))}
            </div>
          ))}
        </div>

        {sug.length > 0 ? (
          <div className="shell-sug">
            {sug.map((s, i) => (
              <button key={s} className={i === sugIdx ? "shell-sug__item active" : "shell-sug__item"} onMouseEnter={() => setSugIdx(i)} onMouseDown={(e) => { e.preventDefault(); applySug(s); }}>
                {s}
              </button>
            ))}
            <span className="shell-sug__hint">↑↓ 选择 · Tab/Enter 确认 · Esc 关闭</span>
          </div>
        ) : null}

        <div className="shell-prompt">
          <span className="shell-prompt__sigil">❯</span>
          <div className="shell-prompt__field">
            <input
              ref={inputRef}
              className="shell-prompt__input"
              value={input}
              onChange={(e) => { setInput(e.target.value); setSug([]); setSugIdx(-1); }}
              onKeyDown={onKey}
              placeholder={remote ? `输入命令（在「${activeAlias}」远端执行）` : "输入命令（内置 cd/ls/pwd/clear/exit，Tab 补全，↑↓ 历史）"}
              disabled={busy}
              spellCheck={false}
              autoFocus
            />
          </div>
          {busy ? <Loader2 size={13} className="shell-prompt__busy" /> : null}
        </div>
      </div>
    </div>
  );
}
