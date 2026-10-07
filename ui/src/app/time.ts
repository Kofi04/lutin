/** "à l'instant", "il y a 5 min", "hier 14:02": the Qt windows' _relative_time. */
export function relativeTime(iso: string | null, now: Date = new Date()): string {
  if (!iso) return "";
  const then = new Date(iso);
  const seconds = Math.round((now.getTime() - then.getTime()) / 1000);
  if (seconds < 60) return "à l'instant";
  if (seconds < 3600) return `il y a ${Math.floor(seconds / 60)} min`;
  const clock = then.toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit" });
  const day = (d: Date) => new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
  const days = Math.round((day(now) - day(then)) / 86_400_000);
  if (days === 0) return clock;
  if (days === 1) return `hier ${clock}`;
  return then.toLocaleDateString("fr-FR", { day: "numeric", month: "short" });
}
