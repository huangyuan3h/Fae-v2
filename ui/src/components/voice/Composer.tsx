"use client";

import {
  FormEvent,
  KeyboardEvent,
  useEffect,
  useRef,
  useState,
} from "react";

import { Button } from "@/components/ui/Button";
import { IconButton } from "@/components/ui/IconButton";
import { Surface } from "@/components/ui/Surface";
import type { OrbState } from "@/hooks/useVoiceSession";

import { StatusChip } from "./StatusChip";

type Props = {
  orb: OrbState;
  sttAvailable: boolean;
  micActive: boolean;
  onStartMic: () => void;
  onStopMic: () => void;
  onInterrupt: () => void;
  onSubmit: (text: string) => void;
};

export function Composer({
  orb,
  sttAvailable,
  micActive,
  onStartMic,
  onStopMic,
  onInterrupt,
  onSubmit,
}: Props) {
  const [draft, setDraft] = useState("");
  const taRef = useRef<HTMLTextAreaElement | null>(null);
  const canInterrupt = orb === "speaking" || orb === "thinking";

  useEffect(() => {
    const ta = taRef.current;
    if (!ta) return;
    ta.style.height = "auto";
    ta.style.height = `${Math.min(ta.scrollHeight, 240)}px`;
  }, [draft]);

  function submit(e?: FormEvent) {
    e?.preventDefault();
    const text = draft.trim();
    if (!text) return;
    onSubmit(text);
    setDraft("");
  }

  function onKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key !== "Enter" || e.shiftKey || e.nativeEvent.isComposing) return;
    e.preventDefault();
    submit();
  }

  return (
    <Surface
      tone="raised"
      className="fae-composer sticky bottom-0 z-10 mx-auto flex w-full max-w-2xl flex-col gap-2 p-2 sm:p-2.5"
      data-testid="composer"
    >
      <div className="flex items-center gap-2">
        <StatusChip state={orb} />
        {!sttAvailable && (
          <span className="text-[11px] text-[var(--ink-soft)]" data-testid="composer-stt-warning">
            无 Web Speech STT
          </span>
        )}
      </div>
      <form onSubmit={submit} className="flex items-end gap-2">
        <textarea
          ref={taRef}
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={onKeyDown}
          rows={1}
          placeholder="输入消息… Enter 发送，Shift+Enter 换行"
          data-testid="composer-textarea"
          className="min-h-10 max-h-60 min-w-0 flex-1 resize-none rounded-xl border border-black/10 bg-white/80 px-3 py-2 text-sm leading-6 outline-none focus:border-[var(--accent)]"
        />
        {canInterrupt ? (
          <IconButton
            label="打断"
            size="md"
            onClick={onInterrupt}
            data-testid="composer-interrupt"
          >
            <span className="text-base" aria-hidden>
              ⏹
            </span>
          </IconButton>
        ) : sttAvailable ? (
          <IconButton
            label={micActive ? "停止听写" : "开始听写"}
            size="md"
            active={micActive}
            onClick={() => (micActive ? onStopMic() : onStartMic())}
            data-testid="composer-mic"
          >
            <span className="text-base" aria-hidden>
              {micActive ? "■" : "🎙"}
            </span>
          </IconButton>
        ) : null}
        <Button
          type="submit"
          variant="primary"
          size="md"
          disabled={!draft.trim()}
          data-testid="composer-send"
          className="shrink-0"
        >
          发送
        </Button>
      </form>
    </Surface>
  );
}