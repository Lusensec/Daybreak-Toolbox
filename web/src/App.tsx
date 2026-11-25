import { lazy, Suspense } from "react";
import { Routes, Route } from "react-router";
import AppShell from "./components/AppShell";
import { PlaceholderPage } from "./pages/PlaceholderPage";
import { HomePage } from "./pages/HomePage";

/** 路由级懒加载：各页面拆成独立 chunk，首包只含 首页 + 壳（页面私有依赖也随之出包）。
 *  子窗口（FloatingWindow → menuContent）对同名页面复用同一 chunk（vite 按模块去重）。 */
const AiChat = lazy(() => import("./features/ai/AiChat").then((m) => ({ default: m.AiChat })));
const TranslatePanel = lazy(() => import("./features/translate/TranslatePanel").then((m) => ({ default: m.TranslatePanel })));
const CodecPanel = lazy(() => import("./features/codec/CodecPanel").then((m) => ({ default: m.CodecPanel })));
const ShellPanel = lazy(() => import("./features/shell/ShellPanel").then((m) => ({ default: m.ShellPanel })));
const NoteEditor = lazy(() => import("./features/note/NoteEditor").then((m) => ({ default: m.NoteEditor })));
const ToolCanvas = lazy(() => import("./pages/ToolCanvas").then((m) => ({ default: m.ToolCanvas })));

/** 懒块加载中的占位（本地 127.0.0.1 毫秒级；用已有样式类，不引入额外 CSS） */
function PageLoader() {
  return <div className="tool-canvas__empty" style={{ padding: 24 }}>加载页面中…</div>;
}

export default function App() {
  return (
    <Suspense fallback={<PageLoader />}>
      <Routes>
        <Route element={<AppShell />}>
          <Route index element={<HomePage />} />
          <Route path="ai" element={<AiChat />} />
          <Route path="translate" element={<TranslatePanel />} />
          <Route path="codec" element={<CodecPanel />} />
          <Route path="shell" element={<ShellPanel />} />
          <Route path="note" element={<NoteEditor />} />
          {/* 数据驱动工具画布：/tools/:menu/:nav（nav 可缺省=首页） */}
          <Route path="tools/:menu" element={<ToolCanvas />} />
          <Route path="tools/:menu/:nav" element={<ToolCanvas />} />
          <Route path="*" element={<PlaceholderPage title="404" hint="路由不存在" />} />
        </Route>
      </Routes>
    </Suspense>
  );
}
