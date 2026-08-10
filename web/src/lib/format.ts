export function formatRelative(iso: string): string {
  const then = new Date(iso).getTime();
  const seconds = Math.round((Date.now() - then) / 1000);
  if (seconds < 5) return "just now";
  if (seconds < 60) return `${seconds}s ago`;
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.round(hours / 24);
  return `${days}d ago`;
}

export function formatTime(iso: string): string {
  return new Date(iso).toLocaleTimeString(undefined, {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

export function formatNumber(value: number): string {
  return new Intl.NumberFormat().format(value);
}

export function shortHash(hash: string | null | undefined): string {
  return hash ? hash.slice(0, 12) : "—";
}

function isInvisible(codePoint: number): boolean {
  return (
    (codePoint >= 0xe0000 && codePoint <= 0xe007f) ||
    (codePoint >= 0x200b && codePoint <= 0x200f) ||
    (codePoint >= 0x202a && codePoint <= 0x202e) ||
    (codePoint >= 0x2060 && codePoint <= 0x2069) ||
    (codePoint >= 0xfe00 && codePoint <= 0xfe0f) ||
    (codePoint >= 0xe0100 && codePoint <= 0xe01ef) ||
    codePoint === 0xfeff ||
    codePoint === 0x180e ||
    codePoint === 0x061c
  );
}

/** Mirror of the backend's reveal_invisible: show the code points a model reads but a reviewer cannot see. */
export function revealInvisible(text: string): string {
  let out = "";
  for (const char of text) {
    const codePoint = char.codePointAt(0) ?? 0;
    out += isInvisible(codePoint) ? `⟦U+${codePoint.toString(16).toUpperCase().padStart(4, "0")}⟧` : char;
  }
  return out;
}
