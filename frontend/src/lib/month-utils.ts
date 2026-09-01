const MONTH_NAMES = [
  "January", "February", "March", "April", "May", "June",
  "July", "August", "September", "October", "November", "December",
];

export function currentMonth(): string {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
}

export function prevMonth(m: string): string {
  const { year, month } = parseMonth(m);
  if (month === 1) return `${year - 1}-12`;
  return `${year}-${String(month - 1).padStart(2, "0")}`;
}

export function nextMonth(m: string): string {
  const { year, month } = parseMonth(m);
  if (month === 12) return `${year + 1}-01`;
  return `${year}-${String(month + 1).padStart(2, "0")}`;
}

export function formatMonthLabel(m: string): string {
  const { year, month } = parseMonth(m);
  return `${MONTH_NAMES[month - 1]} ${year}`;
}

export function formatMonthShort(m: string): string {
  const { year, month } = parseMonth(m);
  return `${MONTH_NAMES[month - 1].slice(0, 3)} ${year}`;
}

export function isFutureMonth(m: string): boolean {
  return m > currentMonth();
}

export function isCurrentMonth(m: string): boolean {
  return m === currentMonth();
}

export function parseMonth(m: string): { year: number; month: number } {
  return { year: parseInt(m.slice(0, 4)), month: parseInt(m.slice(5, 7)) };
}
