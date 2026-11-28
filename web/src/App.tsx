import { lazy, Suspense } from "react";
import { Routes, Route } from "react-router";
import AppShell from "./components/AppShell";
import FloatShell from "./features/floating/FloatShell";
import { PlaceholderPage } from "./pages/PlaceholderPage";
import { HomePage } from "./pages/HomePage";

/** 路由级懒加载：工具画布拆成独立 chunk，首包只含 首页 + 壳。
 *  v2.1.3：系统固定功能面板（AI 对话 / 终端管理 / 编解码 / 汉英翻译 / 临时笔记）已移除，
 *  仅保留 首页 与 数据驱动的工具画布（/tools/:menu/:nav）。 */
const ToolCanvas = lazy(() => import("./pages/ToolCanvas").then((m) => ({ default: m.ToolCanvas })));
/** 内置浏览器页同样懒加载：仅在打开「链接打开」类工具时才需要 */
const BrowserPage = lazy(() => import("./pages/BrowserPage").then((m) => ({ default: m.BrowserPage })));

/** 懒块加载中的占位（本地 127.0.0.1 毫秒级；用已有样式类，不引入额外 CSS） */
function PageLoader() {
  return <div className="tool-canvas__empty" style={{ padding: 24 }}>加载页面中…</div>;
}

/** 原生浮动子窗口（bridge/float_service.py 创建）加载同一 SPA，用 ?float=1 区分渲染分支 */
const IS_FLOAT_WINDOW =
  typeof window !== "undefined" && new URLSearchParams(window.location.search).get("float") === "1";

export default function App() {
  if (IS_FLOAT_WINDOW) {
    return (
      <Suspense fallback={<PageLoader />}>
        <FloatShell />
      </Suspense>
    );
  }
  return (
    <Suspense fallback={<PageLoader />}>
      <Routes>
        <Route element={<AppShell />}>
          <Route index element={<HomePage />} />
          {/* 数据驱动工具画布：/tools/:menu/:nav（nav 可缺省=首页） */}
          <Route path="tools/:menu" element={<ToolCanvas />} />
          <Route path="tools/:menu/:nav" element={<ToolCanvas />} />
          {/* 内置浏览器：/browser/:menu/:name（多标签常驻，iframe 按标签挂载） */}
          <Route path="browser/:menu/:name" element={<BrowserPage />} />
          <Route path="*" element={<PlaceholderPage title="404" hint="路由不存在" />} />
        </Route>
      </Routes>
    </Suspense>
  );
}
