"use client";

import DailyIframe, { type DailyCall } from "@daily-co/daily-js";

export async function joinDailyRoom(
  roomUrl: string,
  token: string,
): Promise<DailyCall> {
  const existing = DailyIframe.getCallInstance();
  if (existing) {
    await existing.destroy();
  }
  const call = DailyIframe.createCallObject({
    audioSource: true,
    videoSource: false,
  });
  await call.join({ url: roomUrl, token });
  return call;
}

export async function leaveDailyRoom(call: DailyCall | null): Promise<void> {
  if (!call) return;
  try {
    await call.leave();
  } finally {
    await call.destroy();
  }
}
