import { useCallback, useMemo, useState } from "react";
import { ArrowDown, ArrowUp, ChevronDown, ChevronLeft, ChevronUp, DollarSign, Pencil, Pin, PinOff, Plus, Sparkles, Trash2, X } from "lucide-react";
import { Layout } from "../components/Layout";
import { MonthSelector } from "../components/MonthSelector";
import { Button } from "../components/ui/button";
import { Label } from "../components/ui/label";
import { SegmentedControl } from "../components/ui/segmented-control";
import { Dialog, DialogTitle } from "../components/ui/dialog";
import { CategoryPicker } from "../components/CategoryPicker";
import { MoneyInput, formatCents } from "../components/MoneyInput";
import {
  useBudgets,
  useBudgetStatus,
  useCreateBudget,
  useDeleteBudget,
  useIncomeSummary,
  useMonthComparison,
  useSeedMonth,
  useSpendingSuggestions,
  useUnbudgetedSpend,
  useUpdateBudget,
} from "../hooks/useBudgets";
import { useCategories } from "../hooks/useCategories";
import { useTransactions } from "../hooks/useTransactions";
import { currentMonth, formatMonthLabel } from "../lib/month-utils";
import type { Budget, BudgetStatusItem, IncomeSummary as IncomeSummaryType, MonthComparisonItem } from "../types/models";
import { cn } from "../lib/utils";

interface FormState {
  id?: number;
  category_id: number | null;
  amount_cents: number;
}

const emptyForm: FormState = {
  category_id: null,
  amount_cents: 0,
};

const viewOptions: Array<{ value: "plan" | "track"; label: string }> = [
  { value: "plan", label: "Plan" },
  { value: "track", label: "Track" },
];

export default function Budgets() {
  const [month, setMonth] = useState(currentMonth);
  const { data: budgets = [], isLoading } = useBudgets(month);
  const { data: status = [] } = useBudgetStatus(month);
  const { data: categories = [] } = useCategories();
  const { data: suggestions = [] } = useSpendingSuggestions(3);
  const { data: incomeSummary } = useIncomeSummary(month);
  const { data: unbudgetedData } = useUnbudgetedSpend(month);
  const { data: comparison } = useMonthComparison(month);
  const createMut = useCreateBudget();
  const updateMut = useUpdateBudget();
  const deleteMut = useDeleteBudget();
  const seedMut = useSeedMonth();

  const [view, setView] = useState<"plan" | "track">("track");
  const [modalOpen, setModalOpen] = useState(false);
  const [form, setForm] = useState<FormState>(emptyForm);
  const [sliderEdits, setSliderEdits] = useState<Record<number, number>>({});
  const [selectedCategoryId, setSelectedCategoryId] = useState<number | null>(null);

  const catMap = useMemo(
    () => new Map(categories.map((c) => [c.id, c.name])),
    [categories],
  );
  const incomeCatIds = useMemo(
    () => new Set(categories.filter((c) => c.is_income).map((c) => c.id)),
    [categories],
  );
  const statusMap = useMemo(
    () => new Map(status.map((s) => [s.category_id, s])),
    [status],
  );
  const suggestMap = useMemo(
    () => new Map(suggestions.map((s) => [s.category_id, s])),
    [suggestions],
  );
  const comparisonMap = useMemo(() => {
    if (!comparison) return new Map<number, MonthComparisonItem>();
    return new Map(comparison.items.map((c) => [c.category_id, c]));
  }, [comparison]);

  const totalBudgeted = budgets.reduce((sum, b) => {
    const edited = sliderEdits[b.id];
    return sum + (edited !== undefined ? edited : b.amount_cents);
  }, 0);
  const totalSpent = status.reduce((sum, s) => sum + s.spent_cents, 0);
  const unbudgetedTotal = unbudgetedData?.total_cents ?? 0;
  const incomeTotal = incomeSummary?.total_cents ?? 0;

  function openCreate() {
    setForm(emptyForm);
    setModalOpen(true);
  }

  function openEdit(b: Budget) {
    setForm({
      id: b.id,
      category_id: b.category_id,
      amount_cents: b.amount_cents,
    });
    setModalOpen(true);
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!form.category_id) return;
    if (form.id) {
      await updateMut.mutateAsync({
        id: form.id,
        category_id: form.category_id,
        amount_cents: form.amount_cents,
      });
    } else {
      await createMut.mutateAsync({
        category_id: form.category_id,
        amount_cents: form.amount_cents,
        year_month: month,
      });
    }
    setModalOpen(false);
    setForm(emptyForm);
  }

  async function handleDelete(id: number) {
    if (!confirm("Delete this budget?")) return;
    await deleteMut.mutateAsync(id);
  }

  const handleSliderChange = useCallback(
    (budgetId: number, cents: number) => {
      setSliderEdits((prev) => ({ ...prev, [budgetId]: cents }));
    },
    [],
  );

  async function applySuggestion(b: Budget) {
    const sug = suggestMap.get(b.category_id);
    if (!sug) return;
    handleSliderChange(b.id, sug.suggested_cents);
  }

  const hasPendingEdits = Object.keys(sliderEdits).length > 0;

  async function saveAllEdits() {
    for (const b of budgets) {
      const newAmount = sliderEdits[b.id];
      if (newAmount !== undefined && newAmount !== b.amount_cents) {
        await updateMut.mutateAsync({ id: b.id, amount_cents: newAmount });
      }
    }
    setSliderEdits({});
  }

  const createBudgetFromSuggestion = async (catId: number, cents: number) => {
    await createMut.mutateAsync({
      category_id: catId,
      amount_cents: cents,
      year_month: month,
    });
  };

  const existingCategoryIds = new Set(budgets.map((b) => b.category_id));

  return (
    <Layout wide>
      {/* Header */}
      <div className="flex flex-wrap items-center justify-between gap-2 mb-3">
        <h1 className="text-xl font-bold text-gray-900 dark:text-gray-100">Budgets</h1>
        <div className="flex items-center gap-2">
          <MonthSelector month={month} onChange={setMonth} />
          <SegmentedControl value={view} onChange={setView} options={viewOptions} />
          {view === "plan" && (
            <Button size="sm" onClick={openCreate}>
              <Plus className="h-4 w-4 mr-1" />
              Add
            </Button>
          )}
        </div>
      </div>

      {/* Auto-seed banner */}
      {!isLoading && budgets.length === 0 && (
        <SeedBanner month={month} onSeed={() => seedMut.mutate(month)} isPending={seedMut.isPending} />
      )}

      {isLoading ? (
        <p className="text-gray-500 text-sm">Loading…</p>
      ) : view === "plan" ? (
        /* ── Plan View ─────────────────────────────────────── */
        budgets.length === 0 ? (
          <div className="text-center py-8">
            <p className="text-gray-500 text-sm mb-3">
              No budgets for this month. Create one or auto-budget from spending history.
            </p>
            {suggestions.length > 0 && (
              <AutoBudgetPanel
                suggestions={suggestions}
                existingCategoryIds={existingCategoryIds}
                onCreate={createBudgetFromSuggestion}
              />
            )}
          </div>
        ) : (
          <>
            <div className="md:grid md:grid-cols-3 md:gap-6">
              <div className="md:col-span-2 space-y-3">
                {incomeSummary && incomeSummary.total_cents > 0 && (
                  <IncomeBanner incomeSummary={incomeSummary} totalBudgeted={totalBudgeted} />
                )}
                {budgets
                  .slice()
                  .sort((a, b) => {
                    if (a.is_pinned !== b.is_pinned) return a.is_pinned ? -1 : 1;
                    const aIncome = incomeCatIds.has(a.category_id);
                    const bIncome = incomeCatIds.has(b.category_id);
                    if (aIncome !== bIncome) return aIncome ? -1 : 1;
                    return (catMap.get(a.category_id) ?? "").localeCompare(
                      catMap.get(b.category_id) ?? "",
                    );
                  })
                  .map((b) => {
                    const catName = catMap.get(b.category_id) ?? "Unknown";
                    const sug = suggestMap.get(b.category_id);
                    const edited = sliderEdits[b.id];
                    return (
                      <PlanRow
                        key={b.id}
                        budget={b}
                        catName={catName}
                        currentAmount={edited !== undefined ? edited : b.amount_cents}
                        historicalAvg={sug?.avg_monthly_cents ?? null}
                        isEdited={edited !== undefined}
                        onSliderChange={(v) => handleSliderChange(b.id, v)}
                        onSuggest={() => applySuggestion(b)}
                        onEdit={() => openEdit(b)}
                        onDelete={() => handleDelete(b.id)}
                        onTogglePin={() =>
                          updateMut.mutate({ id: b.id, is_pinned: !b.is_pinned })
                        }
                        hasSuggestion={!!sug}
                      />
                    );
                  })}
              </div>
              <div className="mt-4 md:mt-0">
                <AutoBudgetPanel
                  suggestions={suggestions}
                  existingCategoryIds={existingCategoryIds}
                  onCreate={createBudgetFromSuggestion}
                />
              </div>
            </div>
            {hasPendingEdits && (
              <div className="fixed bottom-16 left-0 right-0 z-10 md:sticky md:bottom-0 md:mt-4">
                <div className="mx-auto max-w-lg md:max-w-none bg-white dark:bg-gray-800 border border-sky-200 dark:border-sky-800 rounded-lg shadow-lg p-3">
                  <Button
                    onClick={saveAllEdits}
                    disabled={updateMut.isPending}
                    className="w-full"
                  >
                    {updateMut.isPending
                      ? "Saving…"
                      : `Save ${Object.keys(sliderEdits).length} budget changes`}
                  </Button>
                </div>
              </div>
            )}
          </>
        )
      ) : (
        /* ── Track View ────────────────────────────────────── */
        budgets.length === 0 ? (
          <div className="text-center py-8">
            <p className="text-gray-500 text-sm">
              No budgets to track for this month — switch to Plan to set up budgets.
            </p>
          </div>
        ) : (
          <>
            <MonthSummaryBanner
              incomeTotal={incomeTotal}
              totalBudgeted={totalBudgeted}
              totalSpent={totalSpent}
              unbudgetedTotal={unbudgetedTotal}
            />
            {(() => {
              const selectedStatus = selectedCategoryId ? statusMap.get(selectedCategoryId) : null;
              const selectedName = selectedCategoryId ? (catMap.get(selectedCategoryId) ?? "Unknown") : "";

              const budgetCards = budgets.map((b) => {
                const catName = catMap.get(b.category_id) ?? "Unknown";
                const st = statusMap.get(b.category_id);
                const comp = comparisonMap.get(b.category_id);
                return (
                  <TrackRow
                    key={b.id}
                    budget={b}
                    catName={catName}
                    statusItem={st ?? null}
                    isIncome={incomeCatIds.has(b.category_id)}
                    selected={b.category_id === selectedCategoryId}
                    priorSpent={comp?.prior_spent_cents ?? null}
                    onClick={() =>
                      setSelectedCategoryId(
                        b.category_id === selectedCategoryId ? null : b.category_id,
                      )
                    }
                  />
                );
              });

              if (selectedCategoryId) {
                const periodStart = selectedStatus?.period_start ?? `${month}-01`;
                const periodEnd = selectedStatus?.period_end ?? (() => {
                  const [y, m] = month.split("-").map(Number);
                  const lastDay = new Date(Date.UTC(y, m, 0)).getUTCDate();
                  return `${y}-${String(m).padStart(2, "0")}-${String(lastDay).padStart(2, "0")}`;
                })();

                return (
                  <div className="md:grid md:grid-cols-5 md:gap-4">
                    <div className="hidden md:block md:col-span-2 space-y-2 md:max-h-[calc(100vh-14rem)] md:overflow-y-auto md:pr-1">
                      {budgetCards}
                    </div>
                    <div className="md:col-span-3">
                      <BudgetTransactionPanel
                        categoryId={selectedCategoryId}
                        categoryName={selectedName}
                        periodStart={periodStart}
                        periodEnd={periodEnd}
                        onReset={() => setSelectedCategoryId(null)}
                      />
                    </div>
                  </div>
                );
              }

              return (
                <div className="md:grid md:grid-cols-2 lg:grid-cols-3 md:gap-3 space-y-3 md:space-y-0">
                  {budgetCards}
                  <UnbudgetedRow
                    totalCents={unbudgetedTotal}
                    items={unbudgetedData?.items ?? []}
                  />
                </div>
              );
            })()}
          </>
        )
      )}

      {/* Create/Edit dialog */}
      <Dialog open={modalOpen} onClose={() => setModalOpen(false)}>
        <DialogTitle>{form.id ? "Edit Budget" : "New Budget"}</DialogTitle>
        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <Label>Category</Label>
            <CategoryPicker
              value={form.category_id}
              onValueChange={(id) => setForm({ ...form, category_id: id })}
            />
          </div>
          <div>
            <Label>Amount</Label>
            <MoneyInput
              valueCents={form.amount_cents}
              onValueChange={(cents) =>
                setForm({ ...form, amount_cents: cents })
              }
            />
          </div>
          <div className="flex justify-end gap-2 pt-2">
            <Button
              type="button"
              variant="outline"
              onClick={() => setModalOpen(false)}
            >
              Cancel
            </Button>
            <Button
              type="submit"
              disabled={
                !form.category_id ||
                createMut.isPending ||
                updateMut.isPending
              }
            >
              {form.id ? "Save" : "Create"}
            </Button>
          </div>
        </form>
      </Dialog>
    </Layout>
  );
}

/* ── Sub-components ──────────────────────────────────────────── */

function SeedBanner({
  month,
  onSeed,
  isPending,
}: {
  month: string;
  onSeed: () => void;
  isPending: boolean;
}) {
  return (
    <div className="rounded-lg border border-sky-200 dark:border-sky-800 bg-sky-50 dark:bg-sky-900/30 p-3 mb-3 flex flex-wrap items-center justify-between gap-2">
      <p className="text-sm text-sky-800 dark:text-sky-300">
        No budgets for {formatMonthLabel(month)}. Copy from the previous month?
      </p>
      <Button size="sm" onClick={onSeed} disabled={isPending}>
        {isPending ? "Copying…" : "Copy budgets"}
      </Button>
    </div>
  );
}

function MonthSummaryBanner({
  incomeTotal,
  totalBudgeted,
  totalSpent,
  unbudgetedTotal,
}: {
  incomeTotal: number;
  totalBudgeted: number;
  totalSpent: number;
  unbudgetedTotal: number;
}) {
  const totalAllSpend = totalSpent + unbudgetedTotal;
  const net = incomeTotal - totalAllSpend;
  const barMax = Math.max(incomeTotal, totalAllSpend, 1);
  const budgetedPct = (totalSpent / barMax) * 100;
  const unbudgetedPct = (unbudgetedTotal / barMax) * 100;

  return (
    <div className={cn(
      "rounded-lg border p-3 mb-3",
      net >= 0 ? "bg-emerald-50 dark:bg-emerald-900/30 border-emerald-200 dark:border-emerald-800" : "bg-red-50 dark:bg-red-900/30 border-red-200 dark:border-red-800",
    )}>
      {/* Desktop: horizontal stat row */}
      <div className="hidden md:flex md:items-end md:justify-between md:gap-4 mb-2">
        <StatCell label="Income" value={formatCents(incomeTotal)} color="text-emerald-700 dark:text-emerald-400" />
        <StatCell label="Budgeted" value={formatCents(totalBudgeted)} color="text-gray-500 dark:text-gray-400" />
        <StatCell label="Actual spend" value={formatCents(totalSpent)} color="text-gray-900 dark:text-gray-100" />
        <StatCell label="Unbudgeted" value={formatCents(unbudgetedTotal)} color="text-amber-700 dark:text-amber-400" />
        <StatCell
          label="Net"
          value={`${net >= 0 ? "+" : ""}${formatCents(net)}`}
          color={net >= 0 ? "text-emerald-700 dark:text-emerald-400" : "text-red-600 dark:text-red-400"}
        />
      </div>
      {/* Mobile: stacked */}
      <div className="md:hidden space-y-1 mb-2">
        <div className="flex justify-between text-sm">
          <span className="text-gray-600 dark:text-gray-400">Income</span>
          <span className="font-semibold tabular-nums text-emerald-700 dark:text-emerald-400">{formatCents(incomeTotal)}</span>
        </div>
        <div className="flex justify-between text-sm">
          <span className="text-gray-600 dark:text-gray-400">Budgeted</span>
          <span className="font-semibold tabular-nums text-gray-500 dark:text-gray-400">{formatCents(totalBudgeted)}</span>
        </div>
        <div className="flex justify-between text-sm">
          <span className="text-gray-600 dark:text-gray-400">Actual spend</span>
          <span className="font-semibold tabular-nums text-gray-900 dark:text-gray-100">{formatCents(totalSpent)}</span>
        </div>
        <div className="flex justify-between text-sm">
          <span className="text-gray-600 dark:text-gray-400">Unbudgeted</span>
          <span className="font-semibold tabular-nums text-amber-700 dark:text-amber-400">{formatCents(unbudgetedTotal)}</span>
        </div>
        <div className="flex justify-between text-sm border-t border-gray-200 dark:border-gray-700 pt-1">
          <span className="text-gray-600 dark:text-gray-400 font-medium">Net</span>
          <span className={cn("font-bold tabular-nums", net >= 0 ? "text-emerald-700 dark:text-emerald-400" : "text-red-600 dark:text-red-400")}>
            {net >= 0 ? "+" : ""}{formatCents(net)}
          </span>
        </div>
      </div>
      {/* Progress bar */}
      <div className="h-2 w-full bg-white/60 dark:bg-gray-700/60 rounded-full overflow-hidden flex">
        <div
          className="h-full bg-sky-500 transition-all"
          style={{ width: `${Math.min(budgetedPct, 100)}%` }}
        />
        <div
          className="h-full bg-amber-400 transition-all"
          style={{ width: `${Math.min(unbudgetedPct, 100 - Math.min(budgetedPct, 100))}%` }}
        />
      </div>
    </div>
  );
}

function StatCell({ label, value, color }: { label: string; value: string; color: string }) {
  return (
    <div>
      <p className="text-xs text-gray-500 dark:text-gray-400">{label}</p>
      <p className={cn("text-sm font-semibold tabular-nums", color)}>{value}</p>
    </div>
  );
}

function UnbudgetedRow({
  totalCents,
  items,
}: {
  totalCents: number;
  items: Array<{ category_id: number | null; category_name: string; spent_cents: number; txn_count: number }>;
}) {
  const [expanded, setExpanded] = useState(false);

  if (totalCents === 0 && items.length === 0) return null;

  const totalTxns = items.reduce((s, i) => s + i.txn_count, 0);

  return (
    <div
      className="rounded-lg border-2 border-dashed border-gray-300 dark:border-gray-600 bg-gray-50 dark:bg-gray-800 p-3 cursor-pointer"
      onClick={() => setExpanded(!expanded)}
    >
      <div className="flex items-center justify-between mb-1">
        <h3 className="font-medium text-sm text-gray-700 dark:text-gray-300">Unbudgeted spending</h3>
        <span className="text-sm font-semibold tabular-nums text-amber-700 dark:text-amber-400">
          {formatCents(totalCents)}
        </span>
      </div>
      <p className="text-xs text-gray-500 mb-1">
        {totalTxns} transaction{totalTxns !== 1 ? "s" : ""} not covered by a budget
      </p>
      {expanded && items.length > 0 && (
        <div className="mt-2 space-y-1">
          {items.map((item, i) => (
            <div
              key={item.category_id ?? `uncategorized-${i}`}
              className="flex items-center justify-between bg-white dark:bg-gray-700 rounded-md px-2.5 py-1.5 text-sm"
            >
              <span className={cn(
                "text-gray-700 dark:text-gray-300",
                item.category_id === null && "italic text-gray-500 dark:text-gray-400",
              )}>
                {item.category_name}
              </span>
              <span className="font-medium tabular-nums text-gray-900 dark:text-gray-100">
                {formatCents(item.spent_cents)}
              </span>
            </div>
          ))}
        </div>
      )}
      {!expanded && items.length > 0 && (
        <p className="text-xs text-gray-400">
          {items.slice(0, 3).map((i) => `${i.category_name} ${formatCents(i.spent_cents)}`).join(" · ")}
          {items.length > 3 && " …"}
        </p>
      )}
    </div>
  );
}

function IncomeBanner({
  incomeSummary,
  totalBudgeted,
}: {
  incomeSummary: IncomeSummaryType;
  totalBudgeted: number;
}) {
  const [expanded, setExpanded] = useState(false);
  const net = incomeSummary.total_cents - totalBudgeted;
  const coversExpenses = net >= 0;

  return (
    <div
      className={cn(
        "rounded-lg border p-3 mb-2",
        coversExpenses
          ? "bg-sky-50 dark:bg-sky-900/30 border-sky-200 dark:border-sky-800"
          : "bg-amber-50 dark:bg-amber-900/30 border-amber-200 dark:border-amber-800",
      )}
    >
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center justify-between"
      >
        <div className="flex items-center gap-1.5">
          <DollarSign className={cn(
            "h-4 w-4",
            coversExpenses ? "text-sky-600" : "text-amber-600",
          )} />
          <span className={cn(
            "text-sm font-medium",
            coversExpenses ? "text-sky-800 dark:text-sky-300" : "text-amber-800 dark:text-amber-300",
          )}>
            Income this month
          </span>
        </div>
        <div className="flex items-center gap-2">
          <span className={cn(
            "text-sm font-semibold tabular-nums",
            coversExpenses ? "text-sky-700 dark:text-sky-400" : "text-amber-700 dark:text-amber-400",
          )}>
            {formatCents(incomeSummary.total_cents)}
          </span>
          {expanded
            ? <ChevronUp className="h-4 w-4 text-gray-400" />
            : <ChevronDown className="h-4 w-4 text-gray-400" />
          }
        </div>
      </button>

      {expanded && (
        <div className="mt-2 space-y-1">
          {incomeSummary.categories.map((cat) => (
            <div
              key={cat.category_id}
              className="flex items-center justify-between bg-white/60 dark:bg-gray-700/60 rounded-md px-2.5 py-1.5 text-sm"
            >
              <span className="text-gray-700 dark:text-gray-300">{cat.category_name}</span>
              <span className="font-medium tabular-nums text-gray-900 dark:text-gray-100">
                {formatCents(cat.amount_cents)}
              </span>
            </div>
          ))}
        </div>
      )}

      <div className="mt-2 flex justify-between text-xs">
        <span className={cn(
          coversExpenses ? "text-sky-600" : "text-amber-600",
        )}>
          {coversExpenses
            ? `${formatCents(net)} above budgeted expenses`
            : `${formatCents(Math.abs(net))} short of budgeted expenses`
          }
        </span>
      </div>
    </div>
  );
}

function PlanRow({
  budget,
  catName,
  currentAmount,
  historicalAvg,
  isEdited,
  onSliderChange,
  onSuggest,
  onEdit,
  onDelete,
  onTogglePin,
  hasSuggestion,
}: {
  budget: Budget;
  catName: string;
  currentAmount: number;
  historicalAvg: number | null;
  isEdited: boolean;
  onSliderChange: (cents: number) => void;
  onSuggest: () => void;
  onEdit: () => void;
  onDelete: () => void;
  onTogglePin: () => void;
  hasSuggestion: boolean;
}) {
  const sliderMax = Math.max(
    currentAmount * 2,
    (historicalAvg ?? 0) * 2,
    50000,
  );
  const histPct =
    historicalAvg && sliderMax > 0
      ? (historicalAvg / sliderMax) * 100
      : null;

  return (
    <div
      className={cn(
        "bg-white dark:bg-gray-800 rounded-lg border p-3",
        isEdited ? "border-sky-300 dark:border-sky-700 shadow-sm" : "border-gray-200 dark:border-gray-700",
      )}
    >
      <div className="flex items-start justify-between mb-2">
        <div className="flex items-center gap-2">
          <h3 className="font-medium text-sm text-gray-900 dark:text-gray-100">{catName}</h3>
          {budget.is_pinned && (
            <Pin className="h-3 w-3 text-sky-500 fill-sky-500" />
          )}
        </div>
        <div className="flex gap-0.5">
          {hasSuggestion && (
            <Button
              variant="ghost"
              size="icon"
              className="h-7 w-7 text-amber-500"
              title="Use suggested amount"
              onClick={onSuggest}
            >
              <Sparkles className="h-3.5 w-3.5" />
            </Button>
          )}
          <Button
            variant="ghost"
            size="icon"
            className={cn(
              "h-7 w-7",
              budget.is_pinned ? "text-sky-600" : "text-gray-400",
            )}
            onClick={onTogglePin}
          >
            {budget.is_pinned ? (
              <Pin className="h-3.5 w-3.5 fill-current" />
            ) : (
              <PinOff className="h-3.5 w-3.5" />
            )}
          </Button>
          <Button variant="ghost" size="icon" className="h-7 w-7" onClick={onEdit}>
            <Pencil className="h-3.5 w-3.5" />
          </Button>
          <Button
            variant="ghost"
            size="icon"
            className="h-7 w-7 text-red-500"
            onClick={onDelete}
          >
            <Trash2 className="h-3.5 w-3.5" />
          </Button>
        </div>
      </div>

      <div className="flex justify-end text-xs mb-1">
        <span className={cn("font-medium", isEdited ? "text-sky-600 dark:text-sky-400" : "text-gray-900 dark:text-gray-100")}>
          {formatCents(currentAmount)}
        </span>
      </div>

      <div className="relative mb-1">
        <input
          type="range"
          min={0}
          max={sliderMax}
          step={500}
          value={currentAmount}
          onChange={(e) => onSliderChange(Number(e.target.value))}
          className="w-full h-1.5 accent-sky-500 cursor-pointer"
        />
        {histPct !== null && histPct <= 100 && (
          <div
            className="absolute bottom-0 h-1.5 w-0.5 bg-gray-400 pointer-events-none"
            title={`3-mo avg: ${formatCents(historicalAvg!)}`}
            style={{ left: `${histPct}%` }}
          />
        )}
      </div>

      <div className="flex justify-between text-[11px] text-gray-400 mt-0.5">
        <span>$0</span>
        {historicalAvg !== null && (
          <span>
            3-mo avg: {formatCents(historicalAvg)}
            {currentAmount < historicalAvg && (
              <span className="text-amber-500 ml-1">
                budgeting {Math.round(((historicalAvg - currentAmount) / historicalAvg) * 100)}% below 3-mo avg
              </span>
            )}
          </span>
        )}
        <span>{formatCents(sliderMax)}</span>
      </div>
    </div>
  );
}

function TrackRow({
  budget,
  catName,
  statusItem,
  isIncome,
  selected,
  priorSpent,
  onClick,
}: {
  budget: Budget;
  catName: string;
  statusItem: BudgetStatusItem | null;
  isIncome: boolean;
  selected?: boolean;
  priorSpent: number | null;
  onClick?: () => void;
}) {
  const spent = statusItem?.spent_cents ?? 0;
  const budgeted = statusItem?.budgeted_cents ?? budget.amount_cents;
  const remaining = statusItem?.remaining_cents ?? budgeted;
  const pctUsed = statusItem?.percent_used ?? 0;
  const daysLeft = statusItem?.days_remaining ?? 0;
  const pctBar = budgeted > 0 ? (spent / budgeted) * 100 : 0;

  const delta = priorSpent !== null ? spent - priorSpent : null;

  if (isIncome) {
    return (
      <div
        className={cn(
          "rounded-lg border bg-emerald-50/50 dark:bg-emerald-900/20 p-3 cursor-pointer transition-colors",
          selected ? "border-sky-500 ring-1 ring-sky-500" : "border-emerald-200 dark:border-emerald-800 hover:border-emerald-300",
        )}
        onClick={onClick}
      >
        <div className="flex items-center justify-between mb-2">
          <div className="flex items-center gap-2">
            <h3 className="font-medium text-sm text-emerald-900 dark:text-emerald-300">{catName}</h3>
            <span className="text-[10px] font-medium text-emerald-600 dark:text-emerald-400 bg-emerald-100 dark:bg-emerald-900/40 px-1.5 py-0.5 rounded-full">
              income
            </span>
          </div>
          <span className="text-[11px] text-emerald-500 dark:text-emerald-400">{daysLeft}d left</span>
        </div>

        <div className="w-full bg-emerald-100 dark:bg-emerald-900/40 rounded-full h-2.5 overflow-hidden mb-2">
          <div
            className="h-full rounded-full transition-all bg-emerald-500"
            style={{ width: `${Math.min(pctBar, 100)}%` }}
          />
        </div>

        <div className="flex items-center justify-between text-xs">
          <span className="text-emerald-600">
            {formatCents(spent)} of {formatCents(budgeted)} received
          </span>
          <span className="font-medium tabular-nums text-emerald-700">
            {Math.round(pctUsed)}%
          </span>
        </div>
        {priorSpent !== null && (
          <div className="text-[11px] text-gray-400 mt-1">
            Last month: {formatCents(priorSpent)}
            {delta !== null && delta !== 0 && (
              <TrendIndicator delta={delta} isIncome />
            )}
          </div>
        )}
      </div>
    );
  }

  return (
    <div
      className={cn(
        "bg-white dark:bg-gray-800 rounded-lg border p-3 cursor-pointer transition-colors",
        selected ? "border-sky-500 ring-1 ring-sky-500" : "border-gray-200 dark:border-gray-700 hover:border-gray-300 dark:hover:border-gray-600",
      )}
      onClick={onClick}
    >
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-2">
          <h3 className="font-medium text-sm text-gray-900 dark:text-gray-100">{catName}</h3>
          {budget.is_pinned && (
            <Pin className="h-3 w-3 text-sky-500 fill-sky-500" />
          )}
        </div>
        <span className="text-[11px] text-gray-400">{daysLeft}d left</span>
      </div>

      <div className="w-full bg-gray-100 dark:bg-gray-700 rounded-full h-2.5 overflow-hidden mb-2">
        <div
          className={cn(
            "h-full rounded-full transition-all",
            pctBar > 100 ? "bg-red-500" : pctBar > 80 ? "bg-amber-500" : "bg-sky-500",
          )}
          style={{ width: `${Math.min(pctBar, 100)}%` }}
        />
      </div>

      <div className="flex items-center justify-between text-xs">
        <span className="text-gray-500">
          {formatCents(spent)} of {formatCents(budgeted)}
        </span>
        <div className="flex items-center gap-2">
          <span
            className={cn(
              "font-medium tabular-nums",
              remaining < 0 ? "text-red-600 dark:text-red-400" : "text-gray-900 dark:text-gray-100",
            )}
          >
            {formatCents(remaining)} left
          </span>
          <span
            className={cn(
              "text-[10px] font-medium px-1.5 py-0.5 rounded-full",
              pctBar > 100
                ? "bg-red-100 dark:bg-red-900/40 text-red-700 dark:text-red-300"
                : pctBar > 80
                  ? "bg-amber-100 dark:bg-amber-900/40 text-amber-700 dark:text-amber-300"
                  : "bg-emerald-100 dark:bg-emerald-900/40 text-emerald-700 dark:text-emerald-300",
            )}
          >
            {Math.round(pctUsed)}%
          </span>
        </div>
      </div>
      {priorSpent !== null && (
        <div className="text-[11px] text-gray-400 mt-1">
          Last month: {formatCents(priorSpent)}
          {delta !== null && delta !== 0 && (
            <TrendIndicator delta={delta} />
          )}
        </div>
      )}
    </div>
  );
}

function TrendIndicator({ delta, isIncome }: { delta: number; isIncome?: boolean }) {
  const up = delta > 0;
  const good = isIncome ? up : !up;

  return (
    <span className={cn(
      "inline-flex items-center ml-1",
      good ? "text-emerald-600" : "text-red-500",
    )}>
      {up ? <ArrowUp className="h-3 w-3 inline" /> : <ArrowDown className="h-3 w-3 inline" />}
      <span className="ml-0.5">{formatCents(Math.abs(delta))}</span>
    </span>
  );
}

function AutoBudgetPanel({
  suggestions,
  existingCategoryIds,
  onCreate,
}: {
  suggestions: Array<{
    category_id: number;
    category_name: string;
    avg_monthly_cents: number;
    suggested_cents: number;
    txn_count: number;
    is_income: boolean;
  }>;
  existingCategoryIds: Set<number>;
  onCreate: (categoryId: number, cents: number) => Promise<void>;
}) {
  const unbudgeted = suggestions.filter(
    (s) => !existingCategoryIds.has(s.category_id) && s.suggested_cents > 0,
  );
  const [creating, setCreating] = useState<Set<number>>(new Set());

  if (unbudgeted.length === 0) return null;

  const top = unbudgeted.slice(0, 8);

  async function handleCreate(catId: number, cents: number) {
    setCreating((prev) => new Set(prev).add(catId));
    try {
      await onCreate(catId, cents);
    } finally {
      setCreating((prev) => {
        const next = new Set(prev);
        next.delete(catId);
        return next;
      });
    }
  }

  async function handleCreateAll() {
    for (const s of top) {
      await onCreate(s.category_id, s.suggested_cents);
    }
  }

  return (
    <div className="rounded-lg border border-amber-200 dark:border-amber-800 bg-amber-50/50 dark:bg-amber-900/20 p-3 mb-1">
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-1.5">
          <Sparkles className="h-4 w-4 text-amber-500" />
          <span className="text-sm font-medium text-amber-800 dark:text-amber-300">
            Suggested budgets
          </span>
        </div>
        {top.length > 1 && (
          <button
            onClick={handleCreateAll}
            className="text-xs text-amber-700 hover:text-amber-900 font-medium"
          >
            Add all {top.length}
          </button>
        )}
      </div>
      <p className="text-xs text-amber-700 dark:text-amber-400 mb-2">
        Based on your last 3 months of spending:
      </p>
      <div className="space-y-1.5">
        {top.map((s) => (
          <div
            key={s.category_id}
            className="flex items-center justify-between bg-white dark:bg-gray-800 rounded-md px-2.5 py-1.5 border border-amber-100 dark:border-amber-800/50"
          >
            <div className="min-w-0">
              <span className="text-sm font-medium truncate block">
                {s.category_name}
                {s.is_income && (
                  <span className="ml-1.5 text-[10px] font-medium text-emerald-600 bg-emerald-50 px-1 py-0.5 rounded">
                    income
                  </span>
                )}
              </span>
              <span className="text-[11px] text-gray-400">
                avg {formatCents(s.avg_monthly_cents)}/mo · {s.txn_count} txns
              </span>
            </div>
            <button
              onClick={() => handleCreate(s.category_id, s.suggested_cents)}
              disabled={creating.has(s.category_id)}
              className="text-xs font-medium text-sky-600 hover:text-sky-800 whitespace-nowrap ml-2"
            >
              + {formatCents(s.suggested_cents)}
            </button>
          </div>
        ))}
      </div>
    </div>
  );
}

function BudgetTransactionPanel({
  categoryId,
  categoryName,
  periodStart,
  periodEnd,
  onReset,
}: {
  categoryId: number;
  categoryName: string;
  periodStart: string;
  periodEnd: string;
  onReset: () => void;
}) {
  const endDate = periodEnd.slice(0, 10);
  const params: Record<string, string> = {
    category_id: String(categoryId),
    date_from: periodStart,
    date_to: endDate,
    sort: "posted_at:desc",
    limit: "200",
  };
  const { data, isLoading } = useTransactions(params);
  const items = data?.items ?? [];
  const total = data?.total ?? 0;

  return (
    <div>
      <div className="flex items-center justify-between mb-3">
        <div>
          <button
            onClick={onReset}
            className="flex items-center text-sm text-sky-600 md:hidden mb-1"
          >
            <ChevronLeft className="h-4 w-4" />
            Back to budgets
          </button>
          <h3 className="font-semibold text-sm text-gray-900 dark:text-gray-100">{categoryName}</h3>
          <p className="text-xs text-gray-500">
            {new Date(periodStart).toLocaleDateString()} – {new Date(periodEnd).toLocaleDateString()}
          </p>
        </div>
        <Button variant="outline" size="sm" onClick={onReset} className="hidden md:flex">
          <X className="h-3.5 w-3.5 mr-1" />
          Reset
        </Button>
      </div>

      {isLoading ? (
        <p className="text-gray-500 text-sm">Loading…</p>
      ) : items.length === 0 ? (
        <p className="text-gray-500 text-sm">No transactions in this period.</p>
      ) : (
        <>
          <p className="text-xs text-gray-500 mb-2">
            {items.length < total
              ? `Showing ${items.length} of ${total} transactions`
              : `${total} transaction${total !== 1 ? "s" : ""}`}
            {" · "}
            {formatCents(items.reduce((s, t) => s + t.amount_cents, 0))} total
          </p>
          <div className="divide-y divide-gray-100 dark:divide-gray-700 border border-gray-200 dark:border-gray-700 rounded-lg overflow-hidden">
            {items.map((t) => (
              <div key={t.id} className="flex items-center justify-between px-3 py-2 bg-white dark:bg-gray-800">
                <div className="min-w-0 flex-1">
                  <p className="text-sm font-medium truncate text-gray-900 dark:text-gray-100">
                    {t.merchant_name || t.description || "—"}
                  </p>
                  <p className="text-xs text-gray-500">
                    {new Date(t.posted_at).toLocaleDateString()}
                    {t.merchant_name && t.description && t.merchant_name !== t.description && (
                      <span className="text-gray-400"> · {t.description}</span>
                    )}
                  </p>
                </div>
                <span className="text-sm font-semibold tabular-nums whitespace-nowrap ml-3">
                  {formatCents(t.amount_cents)}
                </span>
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  );
}
