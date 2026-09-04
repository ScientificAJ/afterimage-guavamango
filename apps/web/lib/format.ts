export function compactHash(value?: unknown, width = 8): string {
  const text = String(value ?? "unavailable");
  return text.length > width * 2 ? `${text.slice(0, width)}…${text.slice(-width)}` : text;
}

export function number(value: unknown, digits = 2): string {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed.toFixed(digits) : "—";
}

export function percent(value: unknown): string {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? `${(parsed * 100).toFixed(1)}%` : "—";
}

export function label(value: string): string {
  return value.replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}
