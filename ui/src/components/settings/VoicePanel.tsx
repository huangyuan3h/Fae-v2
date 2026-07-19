"use client";

import { useEffect, useState } from "react";

import { backendHttpBase } from "@/lib/config";
import {
  fetchTtsStatus,
  fetchTtsVoices,
  speakWithLocalTts,
  type TtsStatus,
  type TtsVoiceInfo,
} from "@/lib/qwen-tts";
import {
  DEFAULT_TTS_PREFS,
  loadTtsPrefs,
  saveTtsPrefs,
  type TtsPrefs,
} from "@/lib/tts-prefs";
import { loadPreferDaily, savePreferDaily } from "@/lib/voice-prefs";

type VoiceStatus = {
  daily_configured: boolean;
  qwen_tts_configured?: boolean;
  tts_url?: string;
  tts_model?: string;
  tts_voice?: string;
  hint: string;
};

const PREVIEW_TEXT = "你好，这是语音试听。Hello, this is a voice preview.";

export function VoicePanel() {
  const [preferDaily, setPreferDaily] = useState(false);
  const [voiceStatus, setVoiceStatus] = useState<VoiceStatus | null>(null);
  const [ttsStatus, setTtsStatus] = useState<TtsStatus | null>(null);
  const [statusError, setStatusError] = useState<string | null>(null);
  const [prefs, setPrefs] = useState<TtsPrefs>(DEFAULT_TTS_PREFS);
  const [voices, setVoices] = useState<TtsVoiceInfo[]>([]);
  const [languages, setLanguages] = useState<string[]>([]);
  const [previewing, setPreviewing] = useState(false);
  const [previewError, setPreviewError] = useState<string | null>(null);

  useEffect(() => {
    setPreferDaily(loadPreferDaily());
    setPrefs(loadTtsPrefs());
    void Promise.all([
      fetch(`${backendHttpBase()}/api/voice/status`).then(async (res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return (await res.json()) as VoiceStatus;
      }),
      fetchTtsStatus(),
      fetchTtsVoices().catch(() => null),
    ])
      .then(([voice, tts, voiceList]) => {
        setVoiceStatus(voice);
        setTtsStatus(tts);
        if (voiceList) {
          setVoices(voiceList.voices);
          setLanguages(voiceList.languages);
          const current = loadTtsPrefs();
          // Seed empty prefs from server defaults once.
          if (
            current.voice === DEFAULT_TTS_PREFS.voice &&
            !localStorage.getItem("fae.ttsPrefs")
          ) {
            const seeded = saveTtsPrefs({
              voice: voiceList.defaults.voice || current.voice,
              language: voiceList.defaults.language || current.language,
              speed: voiceList.defaults.speed || current.speed,
            });
            setPrefs(seeded);
          }
        }
        if (loadPreferDaily() && !voice.daily_configured) {
          savePreferDaily(false);
          setPreferDaily(false);
        }
      })
      .catch((e) =>
        setStatusError(e instanceof Error ? e.message : String(e)),
      );
  }, []);

  const updatePrefs = (patch: Partial<TtsPrefs>) => {
    const next = saveTtsPrefs(patch);
    setPrefs(next);
  };

  const runPreview = async () => {
    setPreviewError(null);
    setPreviewing(true);
    try {
      await speakWithLocalTts(PREVIEW_TEXT, {
        voice: prefs.voice,
        speed: prefs.speed,
        language: prefs.language,
      });
    } catch (e) {
      setPreviewError(e instanceof Error ? e.message : String(e));
    } finally {
      setPreviewing(false);
    }
  };

  const ttsReady = Boolean(ttsStatus?.configured && ttsStatus?.natural_speech);
  const dailyReady = voiceStatus?.daily_configured ?? false;
  const ttsUrl =
    ttsStatus?.url ?? voiceStatus?.tts_url ?? "http://127.0.0.1:8880/v1";
  const speechUrl = ttsStatus?.speech_url ?? `${ttsUrl}/audio/speech`;
  const langOptions =
    languages.length > 0
      ? languages
      : ["Chinese", "English", "Auto", "Japanese", "Korean"];
  const voiceOptions =
    voices.length > 0
      ? voices.some((v) => v.id === prefs.voice)
        ? voices
        : [{ id: prefs.voice, name: prefs.voice, language: "" }, ...voices]
      : [{ id: prefs.voice, name: prefs.voice, language: "" }];

  return (
    <section>
      <h2
        className="text-xl font-bold text-[var(--ink)]"
        style={{ fontFamily: "var(--font-display)" }}
      >
        语音
      </h2>
      <p className="mt-1 text-sm text-[var(--ink-soft)]">
        仅本机 TTS。<code>npm run dev</code> 会同时起 Qwen3-TTS（
        <code>:8880</code>）。回复按句切片合成播放；下方参数保存在浏览器并随每次
        speak 下发。
      </p>

      <div className="mt-4 grid gap-2 border border-black/8 bg-white/50 px-4 py-3 text-sm">
        <p>
          上游服务：{" "}
          <span style={{ color: ttsReady ? "var(--accent)" : "var(--danger)" }}>
            {statusError
              ? "无法检测"
              : ttsReady
                ? `已连接 · ${ttsStatus?.model ?? "qwen3-tts"} / ${ttsStatus?.voice ?? "Vivian"}`
                : "未连接"}
          </span>
        </p>
        <p className="text-xs text-[var(--ink-soft)] break-all">
          VLLM_TTS_URL: {ttsUrl}
        </p>
        <p className="text-xs text-[var(--ink-soft)] break-all">
          speech: {speechUrl}
        </p>
        {ttsStatus?.hint && !statusError && (
          <p className="text-xs text-[var(--ink-soft)]">{ttsStatus.hint}</p>
        )}
      </div>

      <div className="mt-6 space-y-4">
        <label className="block text-sm text-[var(--ink)]">
          音色
          <select
            className="mt-1 w-full border border-black/15 bg-white px-3 py-2"
            value={prefs.voice}
            onChange={(e) => updatePrefs({ voice: e.target.value })}
          >
            {voiceOptions.map((v) => (
              <option key={v.id} value={v.id}>
                {v.name}
                {v.language ? ` · ${v.language}` : ""}
              </option>
            ))}
          </select>
        </label>

        <label className="block text-sm text-[var(--ink)]">
          语速{" "}
          <span className="text-[var(--ink-soft)]">{prefs.speed.toFixed(2)}</span>
          <input
            type="range"
            className="mt-2 w-full"
            min={0.8}
            max={1.8}
            step={0.05}
            value={prefs.speed}
            onChange={(e) => updatePrefs({ speed: Number(e.target.value) })}
          />
        </label>

        <label className="block text-sm text-[var(--ink)]">
          语言
          <select
            className="mt-1 w-full border border-black/15 bg-white px-3 py-2"
            value={prefs.language}
            onChange={(e) => updatePrefs({ language: e.target.value })}
          >
            {langOptions.map((lang) => (
              <option key={lang} value={lang}>
                {lang}
              </option>
            ))}
          </select>
        </label>

        <div className="flex flex-wrap items-center gap-3">
          <button
            type="button"
            className="border border-black/20 bg-white px-4 py-2 text-sm text-[var(--ink)] disabled:opacity-50"
            disabled={previewing || !ttsReady}
            onClick={() => void runPreview()}
          >
            {previewing ? "试听中…" : "试听"}
          </button>
          {!ttsReady && (
            <span className="text-xs text-[var(--ink-soft)]">
              上游未就绪时无法试听
            </span>
          )}
        </div>
        {previewError && (
          <p className="text-xs text-[var(--danger)]">{previewError}</p>
        )}
      </div>

      {!ttsReady && !statusError && (
        <div className="mt-4 border border-black/10 bg-white/60 px-4 py-3 text-sm">
          <p className="font-medium text-[var(--ink)]">启动本机 TTS</p>
          <ol className="mt-2 list-decimal space-y-1 pl-5 text-xs text-[var(--ink-soft)]">
            <li>
              首次：<code>npm run setup:tts</code>（安装到{" "}
              <code>.deps/qwen3-tts</code>）
            </li>
            <li>
              预热：<code>npm run prepare:tts</code>（推荐）
            </li>
            <li>
              日常：<code>npm run dev</code>（含 TTS 进程）
            </li>
            <li>
              确认 <code>curl http://127.0.0.1:8880/v1/models</code> 有响应
            </li>
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
