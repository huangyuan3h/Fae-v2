"use client";

import { useEffect, useState } from "react";

import { loadPreferDaily, savePreferDaily } from "@/lib/voice-prefs";

export function VoicePanel() {
  const [preferDaily, setPreferDaily] = useState(false);

  useEffect(() => {
    setPreferDaily(loadPreferDaily());
  }, []);

  return (
    <section>
      <h2
        className="text-xl font-bold text-[var(--ink)]"
        style={{ fontFamily: "var(--font-display)" }}
      >
        语音传输
      </h2>
      <p className="mt-1 text-sm text-[var(--ink-soft)]">
        默认使用浏览器语音；需要时可切换到 Daily / Pipecat。
      </p>

      <label className="mt-6 flex items-start gap-3 text-sm text-[var(--ink)]">
        <input
          type="checkbox"
          className="mt-0.5"
          checked={preferDaily}
          onChange={(e) => {
            const v = e.target.checked;
            setPreferDaily(v);
            savePreferDaily(v);
          }}
        />
        <span>
          优先使用 Daily / Pipecat
          <span className="mt-1 block text-xs text-[var(--ink-soft)]">
            需在服务端配置 DAILY_API_KEY；LLM 仍使用「模型」页中当前选中的配置。
          </span>
        </span>
      </label>
    </section>
  );
}
