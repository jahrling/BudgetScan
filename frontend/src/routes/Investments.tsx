import { useState } from "react";
import { ChevronLeft } from "lucide-react";
import { Layout } from "../components/Layout";
import { SegmentedControl } from "../components/ui/segmented-control";
import { Button } from "../components/ui/button";
import {
  formatCents,
  formatGainCents,
  formatPct,
  formatPrice,
  formatShares,
} from "../components/MoneyInput";
import {
  useInvestmentOverview,
  useHoldings,
  useHoldingDetail,
} from "../hooks/useInvestments";
import type {
  AccountSummary,
  HoldingDetailResponse,
  HoldingSummary,
  InvestmentTransaction as InvTxn,
  LotDetail,
} from "../types/models";
import { cn } from "../lib/utils";

const viewOptions: Array<{ value: "overview" | "holdings"; label: string }> = [
  { value: "overview", label: "Overview" },
  { value: "holdings", label: "Holdings" },
];

// ── Stat tile ────────────────────────────────────────────────────────────

function StatTile({
  label,
  value,
  delta,
  muted,
}: {
  label: string;
  value: string;
  delta?: { value: string; positive: boolean } | null;
  muted?: boolean;
}) {
  return (
    <div className="rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 px-4 py-3">
      <p className="text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
        {label}
      </p>
      <p
        className={cn(
          "text-xl font-semibold mt-1",
          muted
            ? "text-gray-400 dark:text-gray-500"
            : "text-gray-900 dark:text-gray-100"
        )}
      >
        {value}
      </p>
      {delta && (
        <p
          className={cn(
            "text-xs font-medium mt-0.5",
            delta.positive
              ? "text-emerald-600 dark:text-emerald-400"
              : "text-red-600 dark:text-red-400"
          )}
        >
          {delta.positive ? "+" : ""}
          {delta.value}
        </p>
      )}
    </div>
  );
}

// ── Gain color helper ────────────────────────────────────────────────────

function gainColor(cents: number | null | undefined) {
  if (cents == null) return "text-gray-400 dark:text-gray-500";
  if (cents > 0) return "text-emerald-600 dark:text-emerald-400";
  if (cents < 0) return "text-red-600 dark:text-red-400";
  return "text-gray-600 dark:text-gray-400";
}

// ── Overview view ────────────────────────────────────────────────────────

function OverviewView() {
  const { data, isLoading } = useInvestmentOverview();

  if (isLoading) {
    return (
      <p className="text-gray-500 dark:text-gray-400 py-8 text-center">
        Loading...
      </p>
    );
  }

  if (!data || data.holdings_count === 0) {
    return (
      <div className="text-center py-12">
        <p className="text-gray-500 dark:text-gray-400">
          No investment holdings found.
        </p>
        <p className="text-sm text-gray-400 dark:text-gray-500 mt-1">
          Import investment transactions and rebuild lots to see your portfolio.
        </p>
      </div>
    );
  }

  const hasValue = data.total_value_cents != null;

  return (
    <div className="space-y-6">
      {/* Stat tiles */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <StatTile
          label="Total value"
          value={hasValue ? formatCents(data.total_value_cents!) : "—"}
          muted={!hasValue}
        />
        <StatTile
          label="Invested capital"
          value={formatCents(data.invested_capital_cents)}
        />
        <StatTile
          label="Total gain"
          value={
            data.total_gain_cents != null
              ? formatGainCents(data.total_gain_cents)
              : "—"
          }
          delta={
            data.total_gain_cents != null
              ? {
                  value:
                    data.cost_basis_cents > 0
                      ? formatPct(data.total_gain_cents / data.cost_basis_cents)
                      : "—",
                  positive: data.total_gain_cents >= 0,
                }
              : null
          }
          muted={data.total_gain_cents == null}
        />
        <StatTile label="Income received" value={formatCents(data.income_cents)} />
      </div>

      {/* Cost basis and realized gains */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <StatTile label="Cost basis" value={formatCents(data.cost_basis_cents)} />
        <StatTile
          label="Realized gains"
          value={formatGainCents(data.realized_gain_cents)}
        />
        <StatTile
          label="Holdings"
          value={String(data.holdings_count)}
        />
        <StatTile
          label="Accounts"
          value={String(data.accounts.length)}
        />
      </div>

      {/* Accounts table */}
      {data.accounts.length > 0 && (
        <div className="rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 overflow-hidden">
          <div className="px-4 py-3 border-b border-gray-100 dark:border-gray-700">
            <h2 className="text-sm font-semibold text-gray-900 dark:text-gray-100">
              Accounts
            </h2>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-gray-100 dark:border-gray-700 text-xs text-gray-500 dark:text-gray-400 uppercase tracking-wider">
                  <th className="px-4 py-2 text-left font-medium">Account</th>
                  <th className="px-4 py-2 text-left font-medium">Type</th>
                  <th className="px-4 py-2 text-right font-medium">Value</th>
                  <th className="px-4 py-2 text-right font-medium">Invested</th>
                  <th className="px-4 py-2 text-right font-medium">Gain</th>
                  <th className="px-4 py-2 text-right font-medium">Holdings</th>
                </tr>
              </thead>
              <tbody>
                {data.accounts.map((a: AccountSummary) => (
                  <tr
                    key={a.id}
                    className="border-b border-gray-50 dark:border-gray-700/50 last:border-b-0"
                  >
                    <td className="px-4 py-2.5 font-medium text-gray-900 dark:text-gray-100">
                      {a.name}
                    </td>
                    <td className="px-4 py-2.5 text-gray-500 dark:text-gray-400">
                      {a.type}
                    </td>
                    <td className="px-4 py-2.5 text-right font-variant-numeric tabular-nums text-gray-900 dark:text-gray-100">
                      {a.value_cents != null ? formatCents(a.value_cents) : "—"}
                    </td>
                    <td className="px-4 py-2.5 text-right font-variant-numeric tabular-nums text-gray-600 dark:text-gray-400">
                      {formatCents(a.invested_capital_cents)}
                    </td>
                    <td
                      className={cn(
                        "px-4 py-2.5 text-right font-variant-numeric tabular-nums",
                        gainColor(a.gain_cents)
                      )}
                    >
                      {a.gain_cents != null
                        ? formatGainCents(a.gain_cents)
                        : "—"}
                    </td>
                    <td className="px-4 py-2.5 text-right text-gray-600 dark:text-gray-400">
                      {a.holdings_count}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}

// ── Holdings view ────────────────────────────────────────────────────────

function HoldingsView({
  onSelect,
}: {
  onSelect: (h: { securityId: number; accountId: number }) => void;
}) {
  const { data: holdings = [], isLoading } = useHoldings();

  if (isLoading) {
    return (
      <p className="text-gray-500 dark:text-gray-400 py-8 text-center">
        Loading...
      </p>
    );
  }

  if (holdings.length === 0) {
    return (
      <div className="text-center py-12">
        <p className="text-gray-500 dark:text-gray-400">
          No holdings found.
        </p>
        <p className="text-sm text-gray-400 dark:text-gray-500 mt-1">
          Import investment transactions and rebuild lots to populate holdings.
        </p>
      </div>
    );
  }

  // Group by account
  const byAccount = new Map<number, { name: string; type: string; items: HoldingSummary[] }>();
  for (const h of holdings) {
    let group = byAccount.get(h.account_id);
    if (!group) {
      group = { name: h.account_name, type: h.account_type, items: [] };
      byAccount.set(h.account_id, group);
    }
    group.items.push(h);
  }

  return (
    <div className="space-y-4">
      {Array.from(byAccount.entries()).map(([accountId, group]) => (
        <div
          key={accountId}
          className="rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 overflow-hidden"
        >
          <div className="px-4 py-3 border-b border-gray-100 dark:border-gray-700">
            <h2 className="text-sm font-semibold text-gray-900 dark:text-gray-100">
              {group.name}
            </h2>
            <p className="text-xs text-gray-400 dark:text-gray-500 mt-0.5">
              {group.type}
            </p>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-gray-100 dark:border-gray-700 text-xs text-gray-500 dark:text-gray-400 uppercase tracking-wider">
                  <th className="px-4 py-2 text-left font-medium">Security</th>
                  <th className="px-4 py-2 text-right font-medium">Qty</th>
                  <th className="px-4 py-2 text-right font-medium">Price</th>
                  <th className="px-4 py-2 text-right font-medium">Value</th>
                  <th className="px-4 py-2 text-right font-medium">Basis</th>
                  <th className="px-4 py-2 text-right font-medium">Invested</th>
                  <th className="px-4 py-2 text-right font-medium">Gain</th>
                  <th className="px-4 py-2 text-right font-medium">Gain %</th>
                  <th className="px-4 py-2 text-right font-medium">Income</th>
                </tr>
              </thead>
              <tbody>
                {group.items.map((h) => {
                  const gainPct =
                    h.unrealized_gain_cents != null && h.cost_basis_cents > 0
                      ? h.unrealized_gain_cents / h.cost_basis_cents
                      : null;

                  return (
                    <tr
                      key={`${h.security_id}-${h.account_id}`}
                      onClick={() =>
                        onSelect({
                          securityId: h.security_id,
                          accountId: h.account_id,
                        })
                      }
                      className="border-b border-gray-50 dark:border-gray-700/50 last:border-b-0 cursor-pointer hover:bg-gray-50 dark:hover:bg-gray-700/50 transition-colors"
                    >
                      <td className="px-4 py-2.5">
                        <div className="font-medium text-gray-900 dark:text-gray-100">
                          {h.symbol || h.security_name}
                        </div>
                        {h.symbol && (
                          <div className="text-xs text-gray-400 dark:text-gray-500 truncate max-w-[200px]">
                            {h.security_name}
                          </div>
                        )}
                      </td>
                      <td className="px-4 py-2.5 text-right tabular-nums text-gray-600 dark:text-gray-400">
                        {formatShares(h.quantity_micros)}
                      </td>
                      <td className="px-4 py-2.5 text-right tabular-nums text-gray-600 dark:text-gray-400">
                        {h.latest_price_micros != null
                          ? formatPrice(h.latest_price_micros)
                          : "—"}
                      </td>
                      <td className="px-4 py-2.5 text-right tabular-nums font-medium text-gray-900 dark:text-gray-100">
                        {h.market_value_cents != null
                          ? formatCents(h.market_value_cents)
                          : "—"}
                      </td>
                      <td className="px-4 py-2.5 text-right tabular-nums text-gray-600 dark:text-gray-400">
                        {formatCents(h.cost_basis_cents)}
                      </td>
                      <td className="px-4 py-2.5 text-right tabular-nums text-gray-600 dark:text-gray-400">
                        {formatCents(h.invested_capital_cents)}
                      </td>
                      <td
                        className={cn(
                          "px-4 py-2.5 text-right tabular-nums",
                          gainColor(h.unrealized_gain_cents)
                        )}
                      >
                        {h.unrealized_gain_cents != null
                          ? formatGainCents(h.unrealized_gain_cents)
                          : "—"}
                      </td>
                      <td
                        className={cn(
                          "px-4 py-2.5 text-right tabular-nums",
                          gainColor(h.unrealized_gain_cents)
                        )}
                      >
                        {gainPct != null
                          ? `${gainPct < 0 ? "-" : "+"}${formatPct(Math.abs(gainPct))}`
                          : "—"}
                      </td>
                      <td className="px-4 py-2.5 text-right tabular-nums text-gray-600 dark:text-gray-400">
                        {formatCents(h.income_cents)}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      ))}
    </div>
  );
}

// ── Holding detail view ──────────────────────────────────────────────────

function HoldingDetailView({
  securityId,
  accountId,
  onBack,
}: {
  securityId: number;
  accountId?: number;
  onBack: () => void;
}) {
  const { data, isLoading } = useHoldingDetail(securityId, accountId);

  return (
    <Layout wide>
      <div className="space-y-6">
        {/* Header */}
        <div className="flex items-center gap-3">
          <Button variant="ghost" size="sm" onClick={onBack}>
            <ChevronLeft className="h-4 w-4" />
            Back
          </Button>
          {data && (
            <div>
              <h1 className="text-lg font-semibold text-gray-900 dark:text-gray-100">
                {data.security.symbol || data.security.name}
              </h1>
              {data.security.symbol && (
                <p className="text-sm text-gray-500 dark:text-gray-400">
                  {data.security.name}
                  {data.account_name && ` · ${data.account_name}`}
                </p>
              )}
            </div>
          )}
        </div>

        {isLoading && (
          <p className="text-gray-500 dark:text-gray-400 py-8 text-center">
            Loading...
          </p>
        )}

        {data && <HoldingDetailContent data={data} />}
      </div>
    </Layout>
  );
}

function HoldingDetailContent({ data }: { data: HoldingDetailResponse }) {
  const [lotView, setLotView] = useState<"open" | "closed">("open");
  const hasValue = data.market_value_cents != null;

  const openLots = data.lots.filter((l) => l.quantity_micros_remaining > 0);
  const closedLots = data.lots.filter((l) => l.quantity_micros_remaining === 0);
  const displayedLots = lotView === "open" ? openLots : closedLots;

  const lotViewOptions: Array<{ value: "open" | "closed"; label: string }> = [
    { value: "open", label: `Open (${openLots.length})` },
    { value: "closed", label: `Closed (${closedLots.length})` },
  ];

  return (
    <div className="space-y-6">
      {/* Stat tiles */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <StatTile
          label="Market value"
          value={hasValue ? formatCents(data.market_value_cents!) : "—"}
          muted={!hasValue}
        />
        <StatTile label="Shares" value={formatShares(data.quantity_micros)} />
        <StatTile
          label="Unrealized gain"
          value={
            data.unrealized_gain_cents != null
              ? formatGainCents(data.unrealized_gain_cents)
              : "—"
          }
          delta={
            data.unrealized_gain_cents != null && data.cost_basis_cents > 0
              ? {
                  value: formatPct(
                    data.unrealized_gain_cents / data.cost_basis_cents
                  ),
                  positive: data.unrealized_gain_cents >= 0,
                }
              : null
          }
          muted={data.unrealized_gain_cents == null}
        />
        <StatTile label="Income" value={formatCents(data.income_cents)} />
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <StatTile label="Cost basis" value={formatCents(data.cost_basis_cents)} />
        <StatTile
          label="Invested capital"
          value={formatCents(data.invested_capital_cents)}
        />
        <StatTile
          label="Realized gains"
          value={formatGainCents(data.realized_gain_cents)}
        />
        <StatTile
          label="Price"
          value={
            data.latest_price_micros != null
              ? formatPrice(data.latest_price_micros)
              : "—"
          }
          muted={data.latest_price_micros == null}
        />
      </div>

      {/* Lots table */}
      <div className="rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 overflow-hidden">
        <div className="px-4 py-3 border-b border-gray-100 dark:border-gray-700 flex items-center justify-between">
          <h2 className="text-sm font-semibold text-gray-900 dark:text-gray-100">
            Tax lots
          </h2>
          <SegmentedControl
            value={lotView}
            onChange={setLotView}
            options={lotViewOptions}
          />
        </div>
        {displayedLots.length === 0 ? (
          <p className="px-4 py-6 text-center text-sm text-gray-400 dark:text-gray-500">
            No {lotView} lots.
          </p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-gray-100 dark:border-gray-700 text-xs text-gray-500 dark:text-gray-400 uppercase tracking-wider">
                  <th className="px-4 py-2 text-left font-medium">Opened</th>
                  <th className="px-4 py-2 text-right font-medium">
                    {lotView === "open" ? "Remaining" : "Original"}
                  </th>
                  <th className="px-4 py-2 text-right font-medium">Basis</th>
                  <th className="px-4 py-2 text-left font-medium">Source</th>
                  <th className="px-4 py-2 text-left font-medium">Type</th>
                </tr>
              </thead>
              <tbody>
                {displayedLots.map((lot: LotDetail) => (
                  <LotRow key={lot.id} lot={lot} showRemaining={lotView === "open"} />
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Transactions table */}
      <div className="rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 overflow-hidden">
        <div className="px-4 py-3 border-b border-gray-100 dark:border-gray-700">
          <h2 className="text-sm font-semibold text-gray-900 dark:text-gray-100">
            Transactions ({data.transactions.length})
          </h2>
        </div>
        {data.transactions.length === 0 ? (
          <p className="px-4 py-6 text-center text-sm text-gray-400 dark:text-gray-500">
            No transactions.
          </p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-gray-100 dark:border-gray-700 text-xs text-gray-500 dark:text-gray-400 uppercase tracking-wider">
                  <th className="px-4 py-2 text-left font-medium">Date</th>
                  <th className="px-4 py-2 text-left font-medium">Action</th>
                  <th className="px-4 py-2 text-right font-medium">Shares</th>
                  <th className="px-4 py-2 text-right font-medium">Price</th>
                  <th className="px-4 py-2 text-right font-medium">Amount</th>
                  <th className="px-4 py-2 text-left font-medium">Memo</th>
                </tr>
              </thead>
              <tbody>
                {data.transactions.map((txn: InvTxn) => (
                  <tr
                    key={txn.id}
                    className="border-b border-gray-50 dark:border-gray-700/50 last:border-b-0"
                  >
                    <td className="px-4 py-2.5 text-gray-900 dark:text-gray-100">
                      {txn.trade_date}
                    </td>
                    <td className="px-4 py-2.5">
                      <ActionBadge action={txn.action} />
                    </td>
                    <td className="px-4 py-2.5 text-right tabular-nums text-gray-600 dark:text-gray-400">
                      {txn.quantity_micros != null
                        ? formatShares(txn.quantity_micros)
                        : "—"}
                    </td>
                    <td className="px-4 py-2.5 text-right tabular-nums text-gray-600 dark:text-gray-400">
                      {txn.price_micros != null
                        ? formatPrice(txn.price_micros)
                        : "—"}
                    </td>
                    <td
                      className={cn(
                        "px-4 py-2.5 text-right tabular-nums",
                        txn.amount_cents > 0
                          ? "text-emerald-600 dark:text-emerald-400"
                          : txn.amount_cents < 0
                            ? "text-red-600 dark:text-red-400"
                            : "text-gray-600 dark:text-gray-400"
                      )}
                    >
                      {txn.amount_cents !== 0
                        ? formatCents(txn.amount_cents)
                        : "—"}
                    </td>
                    <td className="px-4 py-2.5 text-gray-400 dark:text-gray-500 truncate max-w-[200px]">
                      {txn.memo || ""}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}

function LotRow({
  lot,
  showRemaining,
}: {
  lot: LotDetail;
  showRemaining: boolean;
}) {
  return (
    <tr className="border-b border-gray-50 dark:border-gray-700/50 last:border-b-0">
      <td className="px-4 py-2.5 text-gray-900 dark:text-gray-100">
        {lot.opened_at}
      </td>
      <td className="px-4 py-2.5 text-right tabular-nums text-gray-600 dark:text-gray-400">
        {formatShares(
          showRemaining ? lot.quantity_micros_remaining : lot.quantity_micros_original
        )}
      </td>
      <td className="px-4 py-2.5 text-right tabular-nums text-gray-600 dark:text-gray-400">
        {formatCents(lot.cost_basis_cents)}
      </td>
      <td className="px-4 py-2.5 text-gray-500 dark:text-gray-400">
        {lot.source}
      </td>
      <td className="px-4 py-2.5">
        {lot.is_reinvestment ? (
          <span className="inline-flex items-center rounded px-1.5 py-0.5 text-[10px] font-medium bg-violet-100 dark:bg-violet-900/30 text-violet-700 dark:text-violet-300">
            reinvested
          </span>
        ) : (
          <span className="inline-flex items-center rounded px-1.5 py-0.5 text-[10px] font-medium bg-sky-100 dark:bg-sky-900/30 text-sky-700 dark:text-sky-300">
            purchased
          </span>
        )}
      </td>
    </tr>
  );
}

function ActionBadge({ action }: { action: string }) {
  const colors: Record<string, string> = {
    buy: "bg-sky-100 dark:bg-sky-900/30 text-sky-700 dark:text-sky-300",
    sell: "bg-amber-100 dark:bg-amber-900/30 text-amber-700 dark:text-amber-300",
    dividend: "bg-emerald-100 dark:bg-emerald-900/30 text-emerald-700 dark:text-emerald-300",
    reinvest_dividend:
      "bg-emerald-100 dark:bg-emerald-900/30 text-emerald-700 dark:text-emerald-300",
    capital_gain_dist:
      "bg-emerald-100 dark:bg-emerald-900/30 text-emerald-700 dark:text-emerald-300",
    reinvest_capital_gain:
      "bg-emerald-100 dark:bg-emerald-900/30 text-emerald-700 dark:text-emerald-300",
    interest:
      "bg-emerald-100 dark:bg-emerald-900/30 text-emerald-700 dark:text-emerald-300",
    shares_in: "bg-violet-100 dark:bg-violet-900/30 text-violet-700 dark:text-violet-300",
    shares_out:
      "bg-violet-100 dark:bg-violet-900/30 text-violet-700 dark:text-violet-300",
    split: "bg-gray-100 dark:bg-gray-700 text-gray-600 dark:text-gray-400",
  };
  const fallback = "bg-gray-100 dark:bg-gray-700 text-gray-600 dark:text-gray-400";

  const labels: Record<string, string> = {
    buy: "Buy",
    sell: "Sell",
    dividend: "Dividend",
    reinvest_dividend: "Reinv Div",
    capital_gain_dist: "Cap Gain",
    reinvest_capital_gain: "Reinv CG",
    interest: "Interest",
    fee: "Fee",
    shares_in: "Shares In",
    shares_out: "Shares Out",
    cash_in: "Cash In",
    cash_out: "Cash Out",
    split: "Split",
    return_of_capital: "ROC",
    other: "Other",
  };

  return (
    <span
      className={cn(
        "inline-flex items-center rounded px-1.5 py-0.5 text-[10px] font-medium",
        colors[action] || fallback
      )}
    >
      {labels[action] || action}
    </span>
  );
}

// ── Main component ───────────────────────────────────────────────────────

export default function Investments() {
  const [view, setView] = useState<"overview" | "holdings">("overview");
  const [selectedHolding, setSelectedHolding] = useState<{
    securityId: number;
    accountId: number;
  } | null>(null);

  if (selectedHolding) {
    return (
      <HoldingDetailView
        securityId={selectedHolding.securityId}
        accountId={selectedHolding.accountId}
        onBack={() => setSelectedHolding(null)}
      />
    );
  }

  return (
    <Layout wide>
      <div className="space-y-6">
        <div className="flex items-center justify-between">
          <h1 className="text-lg font-semibold text-gray-900 dark:text-gray-100">
            Investments
          </h1>
          <SegmentedControl
            value={view}
            onChange={setView}
            options={viewOptions}
          />
        </div>

        {view === "overview" ? (
          <OverviewView />
        ) : (
          <HoldingsView onSelect={setSelectedHolding} />
        )}
      </div>
    </Layout>
  );
}
