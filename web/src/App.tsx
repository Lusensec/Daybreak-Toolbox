import { lazy, Suspense } from "react";
import { Routes, Route } from "react-router";
import AppShell from "./components/AppShell";
import { PlaceholderPage } from "./pages/PlaceholderPage";
import { HomePage } from "./pages/HomePage";

/** 路由级懒加载：工具画布拆成独立 chunk，首包只含 首页 + 壳。
 *  v2.1.3：系统固定功能面板（AI 对话 / 终端管理 / 编解码 / 汉英翻译 / 临时笔记）已移除，
 *  仅保留 首页 与 数据驱动的工具画布（/tools/:menu/:nav）。 */
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
          {/* 数据驱动工具画布：/tools/:menu/:nav（nav 可缺省=首页） */}
          <Route path="tools/:menu" element={<ToolCanvas />} />
          <Route path="tools/:menu/:nav" element={<ToolCanvas />} />
          <Route path="*" element={<PlaceholderPage title="404" hint="路由不存在" />} />
        </Route>
      </Routes>
    </Suspense>
  );
}
