import { useEffect, useRef, useState } from "react";
import { Save, Trash2, FileText, Plus, Minus } from "lucide-react";
import { useTheme } from "../../theme/ThemeProvider";
import { activePalette } from "../../theme/tokens";
import "./NoteEditor.css";

/** 本地持久化键 */
const LS_KEY = "daybreak.note.content";
const LS_FONT_KEY = "daybreak.note.fontsize";
const FONT_MIN = 10;
const FONT_MAX = 28;
const FONT_DEFAULT = 13;
/** 编辑区内边距（与 CSS .note-area padding 保持一致） */
const PAD_TOP = 8;

function lineH(px: number): number {
  return px + 7; // 13px→20px，与旧版行高比例一致
}

function lineOf(text: string, pos: number): number {
  return text.slice(0, pos).split("\n").length;
}

/**
 * 临时笔记面板（/note）。1:1 复刻 app.py create_note：
 *  - 行号 gutter（左侧 50px 槽，随正文滚动/字号同步）
 *  - 编辑器（Consolas、主题色 note_bg/note_fg/cursor/sel）
 *  - 当前行背景高亮（正文叠加高亮条 + 行号槽 active 行，随光标/滚动同步）
 *  - 字体增大/减小（工具栏，localStorage 持久）
 *  - localStorage 持久（旧版存文件，Web 端用 localStorage）
 *  - 纯前端，不经过 bridge
 */
export function NoteEditor() {
  const { isDark } = useTheme();
  const [content, setContent] = useState<string>(() => {
    try { return localStorage.getItem(LS_KEY) ?? ""; } catch { return ""; }
  });
  const [fontSize, setFontSize] = useState<number>(() => {
    try {
      const v = parseInt(localStorage.getItem(LS_FONT_KEY) ?? "", 10);
      return Number.isFinite(v) && v >= FONT_MIN && v <= FONT_MAX ? v : FONT_DEFAULT;
    } catch { return FONT_DEFAULT; }
  });
  const [dirty, setDirty] = useState(false);
  const [cursorLine, setCursorLine] = useState(1);
  const [scrollTop, setScrollTop] = useState(0);
  const taRef = useRef<HTMLTextAreaElement>(null);
  const gutterRef = useRef<HTMLDivElement>(null);
  const lh = lineH(fontSize);

  // 字体持久化
  useEffect(() => {
    try { localStorage.setItem(LS_FONT_KEY, String(fontSize)); } catch { /* ignore */ }
  }, [fontSize]);

  // 持久化（防抖 400ms）
  useEffect(() => {
    const t = setTimeout(() => {
      try { localStorage.setItem(LS_KEY, content); } catch { /* quota */ }
      setDirty(false);
    }, 400);
    return () => clearTimeout(t);
  }, [content]);

  // 行号 gutter 增量更新（v2.0.12 轻量优化：旧版每次击键全量重建 N 个 div，长笔记 O(N)/键 卡顿）
  const lines = content.split("\n").length;
  const cursorRef = useRef(cursorLine);
  cursorRef.current = cursorLine;

  // ① 全量重建：仅当 行数/主题/字号 变化（O(N) 但很少发生）；重建后补打当前活动行高亮
  useEffect(() => {
    const g = gutterRef.current;
    if (!g) return;
    const p = activePalette();
    g.innerHTML = "";
    const frag = document.createDocumentFragment();
    for (let i = 1; i <= lines; i++) {
      const div = document.createElement("div");
      div.className = "note-line";
      div.textContent = String(i);
      div.style.color = p.noteGutterFg;
      div.style.height = `${lh}px`;
      div.style.lineHeight = `${lh}px`;
      frag.appendChild(div);
    }
    g.appendChild(frag);
    const active = g.children[cursorRef.current - 1] as HTMLElement | undefined;
    if (active) {
      active.classList.add("active");
      active.style.background = p.noteLineHl;
    }
  }, [lines, isDark, lh]);

  // ② 活动行高亮：cursorLine 变化只交换 2 个节点（O(1)；主题/字号变化时随 ① 重建重着色）
  useEffect(() => {
    const g = gutterRef.current;
    if (!g) return;
    const p = activePalette();
    const prev = g.querySelector<HTMLDivElement>(".note-line.active");
    if (prev) {
      prev.classList.remove("active");
      prev.style.background = "";
    }
    const el = g.children[cursorLine - 1] as HTMLElement | undefined;
    if (el && el.classList.contains("note-line")) {
      el.classList.add("active");
      el.style.background = p.noteLineHl;
    }
  }, [cursorLine, isDark, lh]);

  function saveNow() {
    try { localStorage.setItem(LS_KEY, content); } catch { /* ignore */ }
    setDirty(false);
  }
  function clearAll() {
    if (!confirm("确定清空笔记？此操作不可撤销。")) return;
    setContent("");
    setCursorLine(1);
    try { localStorage.removeItem(LS_KEY); } catch { /* ignore */ }
  }
  function bumpFont(delta: number) {
    setFontSize((v) => Math.min(FONT_MAX, Math.max(FONT_MIN, v + delta)));
  }
  function syncCursor(text?: string) {
    const ta = taRef.current;
    if (!ta) return;
    setCursorLine(lineOf(text ?? ta.value, ta.selectionStart ?? 0));
  }

  return (
    <div className="note-editor">
      <div className="note-toolbar">
        <span className="note-brand"><FileText size={15} /> 临时笔记</span>
        <span className="note-hint">{dirty ? "编辑中…" : "已保存"}</span>
        <span className="note-font-tools" title="字体大小">
          <button
            className="note-tool"
            onClick={() => bumpFont(-1)}
            disabled={fontSize <= FONT_MIN}
            title={`缩小字体（当前 ${fontSize}px）`}
          >
            <Minus size={13} />
          </button>
          <span className="note-font-size">{fontSize}px</span>
          <button
            className="note-tool"
            onClick={() => bumpFont(1)}
            disabled={fontSize >= FONT_MAX}
            title={`增大字体（当前 ${fontSize}px）`}
          >
            <Plus size={13} />
          </button>
        </span>
        <button className="note-tool" onClick={saveNow} title="立即保存"><Save size={14} /></button>
        <button className="note-tool danger" onClick={clearAll} title="清空笔记"><Trash2 size={14} /></button>
      </div>

      <div className="note-body">
        <div
          className="note-gutter"
          ref={gutterRef}
          aria-hidden
          style={{ fontSize, lineHeight: `${lh}px` }}
        />
        <div className="note-area-wrap">
          {/* 当前行高亮条：与行号槽 active 行同色，随光标/滚动实时同步 */}
          <div
            className="note-line-hl"
            style={{
              top: PAD_TOP + (cursorLine - 1) * lh - scrollTop,
              height: lh,
            }}
            aria-hidden
          />
          <textarea
            ref={taRef}
            className="note-area"
            value={content}
            onChange={(e) => { setContent(e.target.value); setDirty(true); syncCursor(e.target.value); }}
            onScroll={(e) => {
              const st = e.currentTarget.scrollTop;
              setScrollTop(st);
              const g = gutterRef.current;
              if (g) g.scrollTop = st;
            }}
            onSelect={() => syncCursor()}
            onKeyUp={() => syncCursor()}
            onClick={() => syncCursor()}
            onFocus={() => syncCursor()}
            spellCheck={false}
            placeholder="在此输入临时笔记…"
            style={{ fontSize, lineHeight: `${lh}px` }}
          />
        </div>
      </div>
    </div>
  );
}
