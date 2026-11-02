import { create } from "zustand";

type LangPair = ["en", "zh"] | ["zh", "en"];

interface TranslateState {
  input: string;
  output: string;
  busy: boolean;
  pair: LangPair;
  setInput: (s: string) => void;
  setOutput: (s: string) => void;
  setBusy: (b: boolean) => void;
  togglePair: () => void;
}

/** 1:1 复刻 app.py 的 translation_direction（默认 en→zh，切换 zh→en）。 */
export const useTranslateStore = create<TranslateState>((set) => ({
  input: "",
  output: "",
  busy: false,
  pair: ["en", "zh"],
  setInput: (s) => set({ input: s }),
  setOutput: (s) => set({ output: s }),
  setBusy: (b) => set({ busy: b }),
  togglePair: () =>
    set((st) => ({
      // 元组按引用无法用 === 比较，改按首元素判定当前方向
      pair: st.pair[0] === "en" ? ["zh", "en"] : ["en", "zh"],
    })),
}));
