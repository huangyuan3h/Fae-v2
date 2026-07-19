/** Map browser network failures to an actionable Chinese message. */
export function formatNetworkError(err: unknown, what: string): string {
  const msg = err instanceof Error ? err.message : String(err);
  if (
    msg === "Failed to fetch" ||
    msg.includes("ERR_CONNECTION_REFUSED") ||
    msg.includes("NetworkError")
  ) {
    return `无法连接后端（${what}）。请确认已运行 npm run dev，且 :8000 可访问`;
  }
  return msg;
}
