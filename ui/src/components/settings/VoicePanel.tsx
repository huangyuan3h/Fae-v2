"use client";

import { useEffect, useState } from "react";

import { backendHttpBase } from "@/lib/config";
import { loadPreferDaily, savePreferDaily } from "@/lib/voice-prefs";

type VoiceStatus = {
  daily_configured: boolean;
  dashscope_tts_configured: boolean;
  hint: string;
};

export function VoicePanel() {
  const [preferDaily, setPreferDaily] = useState(false);
  const [status, setStatus] = useState<VoiceStatus | null>(null);
  const [statusError, setStatusError] = useState<string | null>(null);

  useEffect(() => {
    setPreferDaily(loadPreferDaily());
    void fetch(`${backendHttpBase()}/api/voice/status`)
      .then(async (res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return (await res.json()) as VoiceStatus;
      })
      .then(setStatus)
      .catch((e) =>
        setStatusError(e instanceof Error ? e.message : String(e)),
      );
  }, []);

  const dailyReady = status?.daily_configured ?? false;
  const ttsReady = status?.dashscope_tts_configured ?? false;

  return (
    <section>
      <h2
        className="text-xl font-bold text-[var(--ink)]"
        style={{ fontFamily: "var(--font-display)" }}
      >
        语音传输
      </h2>
      <p className="mt-1 text-sm text-[var(--ink-soft)]">
        默认是浏览器朗读（听起来生硬）。更自然的声音走 Daily + DashScope
        Qwen3-TTS。
      </p>

      <div className="mt-4 grid gap-2 border border-black/8 bg-white/50 px-4 py-3 text-sm">
        <p>
          Daily：{" "}
          <span style={{ color: dailyReady ? "var(--accent)" : "var(--danger)" }}>
            {statusError
              ? "无法检测（后端未启动？）"
              : dailyReady
                ? "已配置"
                : "未配置"}
          </span>
        </p>
        <p>
          DashScope TTS：{" "}
          <span style={{ color: ttsReady ? "var(--accent)" : "var(--danger)" }}>
            {statusError ? "—" : ttsReady ? "已配置" : "未配置"}
          </span>
        </p>
        {status?.hint && !statusError && (
          <p className="text-xs text-[var(--ink-soft)]">{status.hint}</p>
        )}
      </div>

      <ol className="mt-5 list-decimal space-y-2 pl-5 text-sm text-[var(--ink)]">
        <li>
          在{" "}
          <a
            href="https://dashboard.daily.co/"
            target="_blank"
            rel="noreferrer"
            className="text-[var(--accent)] underline-offset-2 hover:underline"
          >
            Daily dashboard
          </a>{" "}
          创建 API Key，写入根目录 <code className="text-xs">.env</code>：
          <pre className="mt-1 overflow-x-auto border border-black/8 bg-white/60 px-3 py-2 text-xs text-[var(--ink-soft)]">
            {`DAILY_API_KEY=...
DASHSCOPE_API_KEY=...   # Qwen3-TTS 必填`}
          </pre>
        </li>
        <li>
          重启后端（根目录 <code className="text-xs">npm run dev</code>）。
        </li>
        <li>下方勾选「优先 Daily」，回首页再点麦克风。</li>
      </ol>

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
          优先使用 Daily / Pipecat（服务端 TTS）
          <span className="mt-1 block text-xs text-[var(--ink-soft)]">
            {dailyReady
              ? "已就绪。勾选后回首页按麦克风，会进 WebRTC 房间并用 Qwen TTS 播报。"
              : "先在 .env 配好 DAILY_API_KEY 并重启，勾选才会生效；否则仍会落回浏览器语音。"}
          </span>
        </span>
      </label>
    </section>
  );
}
