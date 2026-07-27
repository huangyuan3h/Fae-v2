"use client";

import { motion } from "framer-motion";

import { Badge } from "@/components/ui/Badge";
import type { OrbState } from "@/hooks/useVoiceSession";

const LABEL: Record<OrbState, { text: string; tone: "neutral" | "accent" | "success" | "warning" }> = {
  idle: { text: "就绪", tone: "neutral" },
  listening: { text: "听写中", tone: "accent" },
  thinking: { text: "思考中", tone: "accent" },
  speaking: { text: "播放中", tone: "success" },
};

const PULSE: Record<OrbState, number[]> = {
  idle: [1, 1.05, 1],
  listening: [1, 1.15, 1],
  thinking: [1, 1.08, 1],
  speaking: [1, 1.12, 0.96, 1.08, 1],
};

const DOT_COLOR: Record<OrbState, string> = {
  idle: "var(--ink-soft)",
  listening: "var(--accent)",
  thinking: "var(--accent)",
  speaking: "#10b981",
};

export function StatusChip({ state }: { state: OrbState }) {
  const meta = LABEL[state];
  return (
    <Badge tone={meta.tone} dot pulse={state !== "idle"}>
      <span className="inline-flex items-center gap-1.5">
        <motion.span
          aria-hidden
          className="h-1.5 w-1.5 rounded-full"
          style={{ background: DOT_COLOR[state] }}
          animate={{ scale: PULSE[state] }}
          transition={{
            duration: state === "speaking" ? 1.2 : 2,
            repeat: Infinity,
            ease: "easeInOut",
          }}
        />
        {meta.text}
      </span>
    </Badge>
  );
}