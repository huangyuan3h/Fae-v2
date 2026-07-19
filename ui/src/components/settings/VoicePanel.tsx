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

  const stubOnly = Boolean(ttsStatus?.embedded);
  const ttsReady =
    ttsStatus?.configured ?? voiceStatus?.qwen_tts_configured ?? false;
  const naturalReady = Boolean(ttsStatus?.natural_speech) && ttsReady && !stubOnly;
  const dailyReady = voiceStatus?.daily_configured ?? false;
  const ttsUrl =
    ttsStatus?.url ?? voiceStatus?.tts_url ?? "http://127.0.0.1:8000/v1";

  return (
    <section>
      <h2
        className="text-xl font-bold text-[var(--ink)]"
        style={{ fontFamily: "var(--font-display)" }}
      >
        语音
      </h2>
      <p className="mt-1 text-sm text-[var(--ink-soft)]">
        默认开发 stub 不会读字（只会哔一声）；聊天会改用浏览器朗读。
        要听自然本地语音，需加载本机 Qwen3-TTS / CosyVoice 权重（见{" "}
        <code>doc/LOCAL_TTS.md</code>）。
      </p>

      <div className="mt-4 grid gap-2 border border-black/8 bg-white/50 px-4 py-3 text-sm">
        <p>
          当前：{" "}
          <span
            style={{
              color: statusError
                ? "var(--danger)"
                : naturalReady
                  ? "var(--accent)"
                  : stubOnly
                    ? "var(--ink-soft)"
                    : "var(--danger)",
            }}
          >
            {statusError
              ? "无法检测"
              : naturalReady
                ? `真模型已连接 · ${ttsStatus?.model ?? "qwen3-tts"} / ${ttsStatus?.voice ?? "Cherry"}`
                : stubOnly
                  ? "内嵌 stub · 提示音（聊天用浏览器读字）"
                  : "未连接"}
          </span>
        </p>
        <p className="text-xs text-[var(--ink-soft)] break-all">URL: {ttsUrl}</p>
        {ttsStatus?.hint && !statusError && (
          <p className="text-xs text-[var(--ink-soft)]">{ttsStatus.hint}</p>
        )}
      </div>

      {stubOnly && !statusError && (
        <div className="mt-4 border border-black/10 bg-white/60 px-4 py-3 text-sm">
          <p className="font-medium text-[var(--ink)]">如何听到自然语音</p>
          <ol className="mt-2 list-decimal space-y-1 pl-5 text-xs text-[var(--ink-soft)]">
            <li>
              按 <code>doc/LOCAL_TTS.md</code> 本机启动 Qwen3-TTS / CosyVoice
            </li>
            <li>
              <code>.env</code>：<code>TTS_EMBED_STUB=false</code>，
              <code>VLLM_TTS_URL</code> 指向该服务
            </li>
            <li>重启 <code>npm run dev</code>，这里应显示「真模型已连接」</li>
          </ol>
        </div>
      )}

      {!ttsReady && !statusError && (
        <div className="mt-4 border border-black/10 bg-white/60 px-4 py-3 text-sm">
          <p className="font-medium text-[var(--ink)]">启动本机 TTS</p>
          <p className="mt-2 text-xs text-[var(--ink-soft)]">
            先 <code>npm run dev</code>；或按 <code>doc/LOCAL_TTS.md</code>{" "}
            配置外部模型服务。
          </p>
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
