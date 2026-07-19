"use client";

import { useEffect, useState } from "react";

import { backendHttpBase } from "@/lib/config";
import { fetchTtsStatus, type TtsStatus } from "@/lib/qwen-tts";
import { loadPreferDaily, savePreferDaily } from "@/lib/voice-prefs";

type VoiceStatus = {
  daily_configured: boolean;
  qwen_tts_configured?: boolean;
  tts_url?: string;
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
        if (loadPreferDaily() && !voice.daily_configured) {
          savePreferDaily(false);
          setPreferDaily(false);
        }
      })
      .catch((e) =>
        setStatusError(e instanceof Error ? e.message : String(e)),
      );
  }, []);

  const ttsReady =
    ttsStatus?.configured ?? voiceStatus?.qwen_tts_configured ?? false;
  const dailyReady = voiceStatus?.daily_configured ?? false;
  const ttsUrl =
    ttsStatus?.url ?? voiceStatus?.tts_url ?? "http://127.0.0.1:8003/v1";

  return (
    <section>
      <h2
        className="text-xl font-bold text-[var(--ink)]"
        style={{ fontFamily: "var(--font-display)" }}
      >
        语音
      </h2>
      <p className="mt-1 text-sm text-[var(--ink-soft)]">
        仅本机 TTS。默认随 <code>npm run dev</code>{" "}
        内嵌 stub（短提示音）；真模型见 <code>doc/LOCAL_TTS.md</code>
        。不提供云端语音合成。
      </p>

      <div className="mt-4 grid gap-2 border border-black/8 bg-white/50 px-4 py-3 text-sm">
        <p>
          本机服务：{" "}
          <span style={{ color: ttsReady ? "var(--accent)" : "var(--danger)" }}>
            {statusError
              ? "无法检测"
              : ttsReady
                ? `已连接 · ${ttsStatus?.model ?? "qwen3-tts"} / ${ttsStatus?.voice ?? "Cherry"}`
                : "未连接"}
          </span>
        </p>
        <p className="text-xs text-[var(--ink-soft)] break-all">URL: {ttsUrl}</p>
        {ttsStatus?.hint && !statusError && (
          <p className="text-xs text-[var(--ink-soft)]">{ttsStatus.hint}</p>
        )}
      </div>

      {!ttsReady && !statusError && (
        <div className="mt-4 border border-black/10 bg-white/60 px-4 py-3 text-sm">
          <p className="font-medium text-[var(--ink)]">启动本机 TTS</p>
          <ol className="mt-2 list-decimal space-y-1 pl-5 text-xs text-[var(--ink-soft)]">
            <li>
              默认：根目录 <code>npm run dev</code>（backend 内嵌 stub）
            </li>
            <li>
              真模型：<code>TTS_EMBED_STUB=false</code>，按{" "}
              <code>doc/LOCAL_TTS.md</code> 起服务并设置{" "}
              <code>VLLM_TTS_URL</code>
            </li>
            <li>重启 backend 后这里应显示「已连接」</li>
          </ol>
        </div>
      )}

      <details className="mt-8 border-t border-black/8 pt-4">
        <summary className="cursor-pointer text-sm text-[var(--ink-soft)]">
          高级：Daily WebRTC（可选）
        </summary>
        <label className="mt-4 flex items-start gap-3 text-sm text-[var(--ink)]">
          <input
            type="checkbox"
            className="mt-0.5"
            checked={preferDaily}
            disabled={!dailyReady}
            onChange={(e) => {
              const v = e.target.checked;
              setPreferDaily(v);
              savePreferDaily(v);
            }}
          />
          <span>
            优先 Daily / Pipecat
            <span className="mt-1 block text-xs text-[var(--ink-soft)]">
              {dailyReady ? "已就绪" : "未配置，可忽略"}
            </span>
          </span>
        </label>
      </details>
    </section>
  );
}
