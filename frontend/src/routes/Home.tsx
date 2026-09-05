import { useMemo, useState } from "react";
import { ChevronDown, ChevronUp, Pin, Wallet } from "lucide-react";
import { Link } from "react-router-dom";
import { Layout } from "../components/Layout";
import { SnapReceiptButton } from "../components/SnapReceiptButton";
import { useBudgetStatus } from "../hooks/useBudgets";
import { currentMonth } from "../lib/month-utils";
import { useTransactions } from "../hooks/useTransactions";
import { formatCents } from "../components/MoneyInput";
import type { BudgetStatusItem, Transaction } from "../types/models";
import { cn } from "../lib/utils";

const TOP_N = 6;

function startOfWeekISO(): string {
  const d = new Date();
  const day = d.getDay(); // 0=Sun
  const diff = (day + 6) % 7; // monday-anchored
  d.setHours(0, 0, 0, 0);
  d.setDate(d.getDate() - diff);
  return d.toISOString();
}

function startOfMonthISO(): string {
  const d = new Date();
  d.setHours(0, 0, 0, 0);
  d.setDate(1);
  return d.toISOString();
}

function pickTop(items: BudgetStatusItem[]): BudgetStatusItem[] {
  const sorted = [...items].sort((a, b) => {
    if (a.is_pinned !== b.is_pinned) return a.is_pinned ? -1 : 1;
    return b.remaining_cents - a.remaining_cents;
  });
  return sorted.slice(0, TOP_N);
}

function colorFor(pct: number): { bar: string; pill: string } {
  if (pct < 0) return { bar: "bg-gray-400", pill: "bg-gray-100 dark:bg-gray-700 text-gray-600 dark:text-gray-400" };
  if (pct < 20) return { bar: "bg-red-500", pill: "bg-red-50 dark:bg-red-900/40 text-red-700 dark:text-red-300" };
  if (pct < 50)
    return { bar: "bg-amber-500", pill: "bg-amber-50 dark:bg-amber-900/40 text-amber-700 dark:text-amber-300" };
  return { bar: "bg-emerald-500", pill: "bg-emerald-50 dark:bg-emerald-900/40 text-emerald-700 dark:text-emerald-300" };
}

function BudgetCard({ b }: { b: BudgetStatusItem }) {
  const pct = b.percent_remaining;
  const c = colorFor(pct);
  const usedPct = Math.min(100, Math.max(0, b.percent_used));
  return (
    <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 px-3 py-2.5 shadow-sm">
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2 min-w-0">
          <span
            className="h-7 w-7 rounded-full flex items-center justify-center text-base shrink-0"
            style={{ backgroundColor: b.category_color ?? "#f1f5f9" }}
            aria-hidden
          >
            <span className="text-sm">{b.category_icon ?? "•"}</span>
          </span>
          <div className="min-w-0">
            <div className="flex items-center gap-1">
              <span className="font-medium text-sm truncate text-gray-900 dark:text-gray-100">
                {b.category_name}
              </span>
              {b.is_pinned && (
                <Pin className="h-3 w-3 text-sky-500 fill-sky-500" />
              )}
            </div>
            <div className="text-[11px] text-gray-500 dark:text-gray-400">
              {b.days_remaining}d left
            </div>
          </div>
        </div>
        <div className="text-right shrink-0">
          <div
            className={cn(
              "font-semibold text-sm tabular-nums",
              b.remaining_cents < 0 ? "text-red-600 dark:text-red-400" : "text-gray-900 dark:text-gray-100",
            )}
          >
            {formatCents(b.remaining_cents)}
          </div>
          <div className="text-[11px] text-gray-500 dark:text-gray-400 tabular-nums">
            of {formatCents(b.budgeted_cents)}
          </div>
        </div>
      </div>
      <div className="mt-2 h-1.5 w-full bg-gray-100 dark:bg-gray-700 rounded-full overflow-hidden">
        <div
          className={cn("h-full rounded-full transition-all", c.bar)}
          style={{ width: `${usedPct}%` }}
        />
      </div>
    </div>
  );
}

function aggregateTopMerchants(
  txns: Transaction[],
): Array<{ name: string; total: number; count: number }> {
  const map = new Map<string, { name: string; total: number; count: number }>();
  for (const t of txns) {
    const name = t.merchant_name ?? t.description ?? "Unknown";
    const cur = map.get(name) ?? { name, total: 0, count: 0 };
    cur.total += t.amount_cents;
    cur.count += 1;
    map.set(name, cur);
  }
  return Array.from(map.values())
    .sort((a, b) => b.total - a.total)
    .slice(0, 5);
}

function formatRelDate(iso: string): string {
  const d = new Date(iso);
  const now = new Date();
  const diffMs = now.getTime() - d.getTime();
  const day = 86400000;
  if (diffMs < day && d.getDate() === now.getDate()) return "Today";
  if (diffMs < 2 * day) return "Yesterday";
  return d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

export default function Home() {
  const { data: statusItems, isLoading, error } = useBudgetStatus(currentMonth());
  const weekStart = useMemo(() => startOfWeekISO(), []);
  const monthStart = useMemo(() => startOfMonthISO(), []);

  const weekTxns = useTransactions({ date_from: weekStart, limit: "100" });
  const monthTxns = useTransactions({ date_from: monthStart, limit: "200" });

  const [txnsOpen, setTxnsOpen] = useState(true);

  const top = useMemo(
    () => (statusItems ? pickTop(statusItems) : []),
    [statusItems],
  );
  const topMerchants = useMemo(
    () => aggregateTopMerchants(monthTxns.data?.items ?? []),
    [monthTxns.data],
  );

  return (
    <Layout>
      {/* Above the fold */}
      <section>
        <div className="flex items-center justify-between mb-2 pt-1">
          <h1 className="text-lg font-semibold text-gray-900 dark:text-gray-100">
            What I can spend
          </h1>
          <Link
            to="/budgets"
            className="text-xs text-sky-600 inline-flex items-center gap-1"
          >
            <Wallet className="h-3.5 w-3.5" />
            All budgets
          </Link>
        </div>

        {isLoading && (
          <div className="space-y-2">
            {Array.from({ length: 4 }).map((_, i) => (
              <div
                key={i}
                className="h-16 bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 animate-pulse"
              />
            ))}
          </div>
        )}

        {error && (
          <p className="text-sm text-red-600 dark:text-red-400">
            Couldn’t load budgets — showing last known values when offline.
          </p>
        )}

        {!isLoading && top.length === 0 && (
          <div className="bg-white dark:bg-gray-800 rounded-xl border border-dashed border-gray-300 dark:border-gray-600 p-6 text-center">
            <p className="text-sm text-gray-600 dark:text-gray-400 mb-3">
              No budgets set up yet.
            </p>
            <Link
              to="/budgets"
              className="text-sm text-sky-600 font-medium"
            >
              Create your first budget →
            </Link>
          </div>
        )}

        <div className="space-y-2 md:grid md:grid-cols-2 md:gap-3 md:space-y-0">
          {top.map((b) => (
            <BudgetCard key={b.budget_id} b={b} />
          ))}
        </div>
      </section>

      {/* Below the fold — side-by-side on desktop */}
      <div className="md:grid md:grid-cols-2 md:gap-6 mt-6 mb-24">
        <section>
          <button
            type="button"
            onClick={() => setTxnsOpen((v) => !v)}
            className="flex w-full items-center justify-between py-2"
          >
            <h2 className="text-sm font-semibold text-gray-700 dark:text-gray-300">
              This week’s transactions
              {weekTxns.data && (
                <span className="ml-2 text-xs font-normal text-gray-500 dark:text-gray-400">
                  {weekTxns.data.items.length}
                </span>
              )}
            </h2>
            {txnsOpen ? (
              <ChevronUp className="h-4 w-4 text-gray-500 dark:text-gray-400" />
            ) : (
              <ChevronDown className="h-4 w-4 text-gray-500 dark:text-gray-400" />
            )}
          </button>
          {txnsOpen && (
            <div className="space-y-1.5">
              {weekTxns.isLoading && (
                <div className="h-12 bg-white dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700 animate-pulse" />
              )}
              {weekTxns.data && weekTxns.data.items.length === 0 && (
                <p className="text-xs text-gray-500 dark:text-gray-400 px-1">
                  Nothing this week yet.
                </p>
              )}
              {weekTxns.data?.items.slice(0, 10).map((t) => (
                <Link
                  key={t.id}
                  to={`/transactions?open=${t.id}`}
                  className="flex items-center justify-between bg-white dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700 px-3 py-2"
                >
                  <div className="min-w-0">
                    <div className="text-sm font-medium text-gray-900 dark:text-gray-100 truncate">
                      {t.merchant_name ?? t.description ?? "Transaction"}
                    </div>
                    <div className="text-[11px] text-gray-500 dark:text-gray-400">
                      {formatRelDate(t.posted_at)}
                    </div>
                  </div>
                  <div className="text-sm font-semibold tabular-nums text-gray-900 dark:text-gray-100">
                    {formatCents(t.amount_cents)}
                  </div>
                </Link>
              ))}
            </div>
          )}
        </section>

        <section className="mt-6 md:mt-0">
          <h2 className="text-sm font-semibold text-gray-700 dark:text-gray-300 py-2">
            Top merchants this period
          </h2>
          {monthTxns.isLoading && (
            <div className="h-12 bg-white dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700 animate-pulse" />
          )}
          {monthTxns.data && topMerchants.length === 0 && (
            <p className="text-xs text-gray-500 dark:text-gray-400 px-1">No spending yet.</p>
          )}
          <div className="space-y-1.5">
            {topMerchants.map((m) => (
              <div
                key={m.name}
                className="flex items-center justify-between bg-white dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700 px-3 py-2"
              >
                <div className="min-w-0">
                  <div className="text-sm font-medium text-gray-900 dark:text-gray-100 truncate">{m.name}</div>
                  <div className="text-[11px] text-gray-500 dark:text-gray-400">
                    {m.count} {m.count === 1 ? "visit" : "visits"}
                  </div>
                </div>
                <div className="text-sm font-semibold tabular-nums text-gray-900 dark:text-gray-100">
                  {formatCents(m.total)}
                </div>
              </div>
            ))}
          </div>
        </section>
      </div>

      <SnapReceiptButton fab label="Snap receipt" />
    </Layout>
  );
}
