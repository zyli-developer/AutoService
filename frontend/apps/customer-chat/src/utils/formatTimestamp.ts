export function formatTimestamp(isoString: string, yesterdayLabel?: string): string {
  if (!isoString) return '';
  const date = new Date(isoString);
  if (isNaN(date.getTime())) return '';

  const now = new Date();
  const pad = (n: number) => String(n).padStart(2, '0');
  const timeStr = `${pad(date.getHours())}:${pad(date.getMinutes())}`;

  const todayStart = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const yesterdayStart = new Date(todayStart.getTime() - 86_400_000);
  const dateStart = new Date(date.getFullYear(), date.getMonth(), date.getDate());

  if (dateStart.getTime() === todayStart.getTime()) {
    return timeStr;
  }
  if (dateStart.getTime() === yesterdayStart.getTime()) {
    const label = yesterdayLabel ?? '昨天';
    return `${label} ${timeStr}`;
  }
  return `${date.getMonth() + 1}/${date.getDate()} ${timeStr}`;
}
