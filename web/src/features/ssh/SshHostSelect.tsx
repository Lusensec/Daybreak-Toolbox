import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router";
import { ChevronDown, Globe, Loader2, Monitor, X } from "lucide-react";
import { useToast } from "../../components/toast";
import { useSshStore } from "./store";
import "./ssh.css";

/**
 * SSH 主机下拉框（终端管理页工具栏，路径芯片与终端类型之间）：
 *  - 触发器：Globe + 当前目标（本地终端 / 别名）+ 箭头；已连接时 accent 描边 + × 断开
 *  - 弹层：工具箱风格自定义列表（本地终端 + 已保存主机；主机行 主行 别名 / 副行 user@host:port）
 *  - 选中别名 = 立即连接（bridge 常驻 paramiko 会话）→ 终端管理页进入远端命令模式
 *  - 选「本地终端」= 断开回本地；连接失败：弹 toast；远端断开会话：自动回落本地
 */
export function SshHostSelect() {
  const hosts = useSshStore((s) => s.hosts);
  const active = useSshStore((s) => s.activeAlias);
  const connecting = useSshStore((s) => s.connecting);
  const select = useSshStore((s) => s.select);
  const navigate = useNavigate();
  const toast = useToast();
  const [open, setOpen] = useState(false);
  const wrapRef = useRef<HTMLDivElement>(null);

  // 点外部 / Esc 收起弹层
  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (wrapRef.current && !wrapRef.current.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  async function pick(alias: string | null) {
    setOpen(false);
    if (alias === null) {
      try {
        await select(null); // 回本地终端
      } catch { /* 断开失败不阻塞本地模式 */ }
      return;
    }
    try {
      await select(alias);
      navigate("/shell"); // 连接成功 → 进入终端管理页（远端命令模式；已在该页则无感）
    } catch (err) {
      toast.err(err instanceof Error ? err.message : String(err));
    }
  }

  const label = active ?? "本地终端";

  return (
    <div className={"ssh-select" + (active ? " is-active" : "") + (connecting ? " is-busy" : "")} ref={wrapRef}>
      <button
        type="button"
        className="ssh-select__trigger"
        title="SSH 主机（终端设置 中维护；选中即连接，命令改在远端执行）"
        disabled={!!connecting}
        onClick={() => setOpen((o) => !o)}
      >
        {connecting
          ? <Loader2 size={13} className="ssh-select__spin" />
          : active
            ? <Globe size={13} />
            : <Monitor size={13} />}
        <span className="ssh-select__label">{connecting ? "连接中…" : label}</span>
        {!connecting ? <ChevronDown size={12} className={"ssh-select__chev" + (open ? " is-open" : "")} /> : null}
      </button>
      {active && !connecting ? (
        <button
          type="button"
          className="ssh-select__close"
          title="断开 SSH，回本地终端"
          onClick={() => { void pick(null); }}
        >
          <X size={11} />
        </button>
      ) : null}

      {open ? (
        <div className="ssh-select__menu">
          <div
            className={"ssh-select__item" + (active === null ? " is-on" : "")}
            onClick={() => { void pick(null); }}
          >
            <span className="ssh-select__item-main"><Monitor size={12} /> 本地终端</span>
            <span className="ssh-select__item-sub">本机命令行（cmd / PowerShell）</span>
          </div>
          {hosts.length > 0 ? <div className="ssh-select__sep" /> : null}
          {hosts.map((h) => (
            <div
              key={h.alias}
              className={"ssh-select__item" + (active === h.alias ? " is-on" : "")}
              onClick={() => { void pick(h.alias); }}
            >
              <span className="ssh-select__item-main"><Globe size={12} /> {h.alias}</span>
              <span className="ssh-select__item-sub">
                {h.username}@{h.host}{(h.port ?? 22) !== 22 ? `:${h.port}` : ""}
              </span>
            </div>
          ))}
          {hosts.length === 0 ? (
            <div className="ssh-select__empty">暂无 SSH 主机——到「工具箱设置 → 终端设置」添加</div>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
