import { Routes, Route } from "react-router";
import AppShell from "./components/AppShell";
import { PlaceholderPage } from "./pages/PlaceholderPage";
import { HomePage } from "./pages/HomePage";
import { ShellPanel } from "./features/shell/ShellPanel";
import { AiChat } from "./features/ai/AiChat";
import { CodecPanel } from "./features/codec/CodecPanel";
import { TranslatePanel } from "./features/translate/TranslatePanel";
import { NoteEditor } from "./features/note/NoteEditor";
import { ToolCanvas } from "./pages/ToolCanvas";

export default function App() {
  return (
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
  );
}
