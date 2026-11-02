import { useEffect, useState } from "react";
import { sendCommand } from "../services/ws";
import "./AboutDialog.css";

interface VersionEntry {
  version: string;
  lines: string[];
}

/**
 * 版本更新记录（1:1 复刻 app.py update_record_show 弹窗）。
 * mount 时拉 update.record（fun.get_update_record_content 的 dict），
 * 按版本倒序（后端已 reverse）渲染。
 */
export function AboutDialog() {
  const [versions, setVersions] = useState<VersionEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState("");

  useEffect(() => {
    let alive = true;
    sendCommand("update.record", {})
      .then((r: Record<string, unknown>) => {
        if (!alive) return;
        const dict = (r.versions ?? {}) as Record<string, string>;
        const list = Object.entries(dict)
          .map(([version, body]) => ({
            version,
            lines: String(body).split("\n").map((l) => l.trim()).filter(Boolean),
          }))
          .sort((a, b) => (a.version < b.version ? 1 : -1)); // 倒序
        setVersions(list);
      })
      .catch((e: unknown) => alive && setErr(String(e)))
      .finally(() => alive && setLoading(false));
    return () => { alive = false; };
  }, []);

  return (
    <div className="about-dialog">
      <h2 className="about-title">📝 版本更新记录</h2>
      {loading && <div className="about-msg">加载中…</div>}
      {err && <div className="about-msg err">获取更新记录失败：{err}</div>}
      {!loading && !err && versions.length === 0 && (
        <div className="about-msg">暂无更新记录</div>
      )}
      {versions.map((v, i) => (
        <div key={v.version} className="about-block">
          <div className="about-version">版本 {v.version}</div>
          <ul className="about-list">
            {v.lines.map((line, j) => (
              <li key={j}>{line}</li>
            ))}
          </ul>
          {i < versions.length - 1 && <div className="about-sep" />}
        </div>
      ))}
    </div>
  );
}
