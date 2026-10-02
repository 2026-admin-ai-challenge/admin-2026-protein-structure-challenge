export const date = (v: string) =>
  new Date(v).toLocaleString("ko-KR", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
export function localTime(value?: string | null) {
  if (!value) return "";
  const d = new Date(value);
  return new Date(d.getTime() - d.getTimezoneOffset() * 60000)
    .toISOString()
    .slice(0, 16);
}
export const count = (n?: number | null) =>
  n === undefined || n === null ? "—" : n.toLocaleString();
export function fileSize(bytes?: number | null) {
  if (bytes === undefined || bytes === null) return "—";
  if (bytes < 1024) return bytes + " B";
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + " KB";
  return (bytes / (1024 * 1024)).toFixed(1) + " MB";
}
export const megabytes = (bytes: number) =>
  Math.round(bytes / (1024 * 1024)).toLocaleString() + " MB";
export const minutes = (seconds: number) =>
  seconds % 60 === 0 ? seconds / 60 + "분" : seconds + "초";
