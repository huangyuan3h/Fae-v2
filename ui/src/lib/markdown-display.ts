/**
 * Prep assistant markdown for display (repair collapsed GFM tables).
 * Models sometimes emit "| a || b |" instead of "| a |\n| b |".
 */
export function normalizeMarkdownForDisplay(text: string): string {
  if (!text) return text;

  const parts = text.split(/(```[\s\S]*?```)/g);
  return parts
    .map((part, i) => {
      // Odd indices are fenced code — leave untouched.
      if (i % 2 === 1) return part;
      let s = part;
      // Collapsed table rows: || → |\n|
      s = s.replace(/\|\|/g, "|\n|");
      // Ensure a blank line before a table that follows prose on the same block
      s = s.replace(/([^\n|])\n(\|)/g, "$1\n\n$2");
      return s;
    })
    .join("");
}
