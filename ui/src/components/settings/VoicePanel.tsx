"use client";

import { useEffect, useState } from "react";

import { backendHttpBase } from "@/lib/config";
import { fetchTtsStatus, type TtsStatus } from "@/lib/qwen-tts";
import { loadPreferDaily, savePreferDaily } from "@/lib/voice-prefs";

type VoiceStatus = {
  daily_configured: boolean;
  qwen_tts_configured?: boolean;
  dashscope_tts_configured: boolean;
  tts_model?: string;
  tts_voice?: string;
  hint: string;
};

export function VoicePanel() {
  const [preferDaily, setPreferDaily] = useState(false);
  const [voiceStatus, setVoiceStatus] = useState<VoiceStatus | null>(null);
  const [ttsStatus, setTtsStatus] = useState<TtsStatus | null>(null);
  const [statusError, setStatusError] = useState<string | null>(null);

  useEffect(() => {
    setPreferDaily(loadPreferDaily());
    void Promise.all([
      fetch(`${backendHttpBase()}/api/voice/status`).then(async (res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return (await res.json()) as VoiceStatus;
      }),
      fetchTtsStatus(),
    ])
      .then(([voice, tts]) => {
        setVoiceStatus(voice);
        setTtsStatus(tts);
      })
      .catch((e) =>
        setStatusError(e instanceof Error ? e.message : String(e)),
      );
  }, []);

  const qwenReady =
    ttsStatus?.configured ??
    voiceStatus?.qwen_tts_configured ??
    voiceStatus?.dashscope_tts_configured ??
    false;
  const dailyReady = voiceStatus?.daily_configured ?? false;

  return (
    <section>
      <h2
        className="text-xl font-bold text-[var(--ink)]"
        style={{ fontFamily: "var(--font-display)" }}
      >
        语音
      </h2>
      <p className="mt-1 text-sm text-[var(--ink-soft)]">
        默认用服务端 <strong>Qwen3-TTS</strong> 播报（不需要 Daily）。识别仍用浏览器。
      </p>

      <div className="mt-4 grid gap-2 border border-black/8 bg-white/50 px-4 py-3 text-sm">
        <p>
          Qwen3-TTS：{" "}
          <span style={{ color: qwenReady ? "var(--accent)" : "var(--danger)" }}>
            {statusError
              ? "无法检测（后端未启动？）"
              : qwenReady
                ? `已配置 · ${ttsStatus?.model ?? "qwen3-tts-flash"} / ${ttsStatus?.voice ?? "Cherry"}`
                : "未配置"}
          </span>
        </p>
        <p>
          Daily（可选 WebRTC）：{" "}
          <span style={{ color: dailyReady ? "var(--accent)" : "var(--ink-soft)" }}>
            {statusError ? "—" : dailyReady ? "已配置" : "未使用"}
          </span>
        </p>
        {!statusError && ttsStatus?.hint && (
          <p className="text-xs text-[var(--ink-soft)]">{ttsStatus.hint}</p>
        )}
      </div>

      <ol className="mt-5 list-decimal space-y-2 pl-5 text-sm text-[var(--ink)]">
        <li>
          根目录 <code className="text-xs">.env</code> 设置：
          <pre className="mt-1 overflow-x-auto border border-black/8 bg-white/60 px-3 py-2 text-xs text-[var(--ink-soft)]">
            {`DASHSCOPE_API_KEY=sk-...
# 可选
# TTS_MODEL=qwen3-tts-flash
# TTS_VOICE=Cherry`}
          </pre>
        </li>
        <li>
          重启后端（<code className="text-xs">npm run dev</code>），回首页说话或打字即可听到 Qwen 音色。
        </li>
      </ol>

      <details className="mt-8 border-t border-black/8 pt-4">
        <summary className="cursor-pointer text-sm text-[var(--ink-soft)]">
          高级：Daily WebRTC（可选）
        </summary>
        <p className="mt-2 text-xs text-[var(--ink-soft)]">
          Daily 只负责房间传输；不配也能用 Qwen3-TTS。需要全双工 WebRTC 时再开。
        </p>
        <label className="mt-4 flex items-start gap-3 text-sm text-[var(--ink)]">
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
              需 <code>DAILY_API_KEY</code>；未配置会回退浏览器路径 + Qwen3-TTS。
            </span>
          </span>
        </label>
      </details>
    </section>
  );
}
