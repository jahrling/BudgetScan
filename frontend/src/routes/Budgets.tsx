import { useCallback, useMemo, useState } from "react";
import { ChevronDown, ChevronUp, DollarSign, Pencil, Pin, PinOff, Plus, Sparkles, Trash2 } from "lucide-react";
import { Layout } from "../components/Layout";
import { Button } from "../components/ui/button";
import { Label } from "../components/ui/label";
import { Select } from "../components/ui/select";
import { Dialog, DialogTitle } from "../components/ui/dialog";
import { CategoryPicker } from "../components/CategoryPicker";
import { MoneyInput, formatCents } from "../components/MoneyInput";
import {
  useBudgets,
  useBudgetStatus,
  useCreateBudget,
  useDeleteBudget,
  useIncomeSummary,
  useSpendingSuggestions,
  useUpdateBudget,
} from "../hooks/useBudgets";
import { useCategories } from "../hooks/useCategories";
import type { Budget, IncomeSummary as IncomeSummaryType } from "../types/models";
import { cn } from "../lib/utils";

interface FormState {
  id?: number;
  category_id: number | null;
  amount_cents: number;
  period: string;
  start_date: string;
}

function todayFirstOfMonth(): string {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-01`;
}

const emptyForm: FormState = {
  category_id: null,
  amount_cents: 0,
  period: "monthly",
  start_date: todayFirstOfMonth(),
};

function healthColor(ratio: number): {
  bg: string;
  border: string;
  text: string;
  label: string;
} {
  if (ratio <= 0.9)
    return {
      bg: "bg-emerald-50",
      border: "border-emerald-200",
      text: "text-emerald-700",
      label: "Healthy",
    };
  if (ratio <= 1.0)
    return {
      bg: "bg-amber-50",
      border: "border-amber-200",
      text: "text-amber-700",
      label: "Tight",
    };
  return {
    bg: "bg-red-50",
    border: "border-red-200",
    text: "text-red-700",
    label: "Over",
  };
}

export default function Budgets() {
  const { data: budgets = [], isLoading } = useBudgets();
  const { data: status = [] } = useBudgetStatus();
  const { data: categories = [] } = useCategories();
  const { data: suggestions = [] } = useSpendingSuggestions(3);
  const { data: incomeSummary } = useIncomeSummary();
  const createMut = useCreateBudget();
  const updateMut = useUpdateBudget();
  const deleteMut = useDeleteBudget();

  const [modalOpen, setModalOpen] = useState(false);
  const [form, setForm] = useState<FormState>(emptyForm);

  // Inline slider edits: budget_id -> new amount
  const [sliderEdits, setSliderEdits] = useState<Record<number, number>>({});

  const catMap = new Map(categories.map((c) => [c.id, c.name]));
  const statusMap = new Map(status.map((s) => [s.category_id, s]));
  const suggestMap = useMemo(
    () => new Map(suggestions.map((s) => [s.category_id, s])),
    [suggestions],
  );

  // Compute totals for health banner
  const totalBudgeted = budgets.reduce((sum, b) => {
    const edited = sliderEdits[b.id];
    return sum + (edited !== undefined ? edited : b.amount_cents);
  }, 0);
  const totalSpent = status.reduce((sum, s) => sum + s.spent_cents, 0);

  function openCreate() {
    setForm(emptyForm);
    setModalOpen(true);
  }

  function openEdit(b: Budget) {
    setForm({
      id: b.id,
      category_id: b.category_id,
      amount_cents: b.amount_cents,
      period: b.period,
      start_date: b.start_date,
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
        period: form.period,
        start_date: form.start_date,
      });
    } else {
      await createMut.mutateAsync({
        category_id: form.category_id,
        amount_cents: form.amount_cents,
        period: form.period,
        start_date: form.start_date,
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

  return (
    <Layout>
      <div className="flex items-center justify-between mb-3">
        <h1 className="text-xl font-bold">Budgets</h1>
        <Button size="sm" onClick={openCreate}>
          <Plus className="h-4 w-4 mr-1" />
          Add
        </Button>
      </div>

      {/* Income + Health banner */}
      {budgets.length > 0 && (
        <>
          {incomeSummary && incomeSummary.total_cents > 0 && (
            <IncomeBanner incomeSummary={incomeSummary} totalBudgeted={totalBudgeted} />
          )}
          <HealthBanner
            totalBudgeted={totalBudgeted}
            totalSpent={totalSpent}
          />
        </>
      )}

      {isLoading ? (
        <p className="text-gray-500 text-sm">Loading…</p>
      ) : budgets.length === 0 ? (
        <div className="text-center py-8">
          <p className="text-gray-500 text-sm mb-3">
            No budgets yet. Create one or auto-budget from spending history.
          </p>
          {suggestions.length > 0 && (
            <AutoBudgetPanel
              suggestions={suggestions}
              existingCategoryIds={new Set(budgets.map((b) => b.category_id))}
              onCreate={async (catId, cents) => {
                await createMut.mutateAsync({
                  category_id: catId,
                  amount_cents: cents,
                  period: "monthly",
                  start_date: todayFirstOfMonth(),
                });
              }}
            />
          )}
        </div>
      ) : (
        <>
          {/* Auto-budget for categories without budgets */}
          {suggestions.length > 0 && (
            <AutoBudgetPanel
              suggestions={suggestions}
              existingCategoryIds={new Set(budgets.map((b) => b.category_id))}
              onCreate={async (catId, cents) => {
                await createMut.mutateAsync({
                  category_id: catId,
                  amount_cents: cents,
                  period: "monthly",
                  start_date: todayFirstOfMonth(),
                });
              }}
            />
          )}

          <div className="space-y-3 mt-3">
            {budgets.map((b) => {
              const catName = catMap.get(b.category_id) ?? "Unknown";
              const st = statusMap.get(b.category_id);
              const sug = suggestMap.get(b.category_id);
              const currentAmount =
                sliderEdits[b.id] !== undefined
                  ? sliderEdits[b.id]
                  : b.amount_cents;
              const isEdited =
                sliderEdits[b.id] !== undefined &&
                sliderEdits[b.id] !== b.amount_cents;

              return (
                <BudgetRow
                  key={b.id}
                  budget={b}
                  catName={catName}
                  spent={st?.spent_cents ?? 0}
                  currentAmount={currentAmount}
                  historicalAvg={sug?.avg_monthly_cents ?? null}
                  isEdited={isEdited}
                  onSliderChange={(cents) => handleSliderChange(b.id, cents)}
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

          {/* Sticky save bar */}
          {hasPendingEdits && (
            <div className="fixed bottom-16 left-0 right-0 z-10 bg-white/95 backdrop-blur border-t border-gray-200 px-4 py-3 md:sticky md:bottom-0 md:mt-3">
              <div className="mx-auto max-w-lg md:max-w-none">
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
          <div>
            <Label>Period</Label>
            <Select
              value={form.period}
              onChange={(e) => setForm({ ...form, period: e.target.value })}
            >
              <option value="monthly">Monthly</option>
              <option value="weekly">Weekly</option>
            </Select>
          </div>
          <div>
            <Label>Start Date</Label>
            <input
              type="date"
              value={form.start_date}
              onChange={(e) =>
                setForm({ ...form, start_date: e.target.value })
              }
              className="flex h-10 w-full rounded-md border border-gray-300 bg-white px-3 py-2 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-500"
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

function HealthBanner({
  totalBudgeted,
  totalSpent,
}: {
  totalBudgeted: number;
  totalSpent: number;
}) {
  const ratio = totalBudgeted > 0 ? totalSpent / totalBudgeted : 0;
  const c = healthColor(ratio);
  const remaining = totalBudgeted - totalSpent;

  return (
    <div
      className={cn(
        "rounded-lg border p-3 mb-3",
        c.bg,
        c.border,
      )}
    >
      <div className="flex items-center justify-between mb-2">
        <span className={cn("text-xs font-medium", c.text)}>
          {c.label}
        </span>
        <span className={cn("text-xs font-medium", c.text)}>
          {Math.round(ratio * 100)}% used
        </span>
      </div>
      <div className="flex justify-between text-sm">
        <div>
          <p className="text-xs text-gray-500">Budgeted</p>
          <p className="font-semibold tabular-nums">{formatCents(totalBudgeted)}</p>
        </div>
        <div className="text-center">
          <p className="text-xs text-gray-500">Spent</p>
          <p className="font-semibold tabular-nums">{formatCents(totalSpent)}</p>
        </div>
        <div className="text-right">
          <p className="text-xs text-gray-500">Remaining</p>
          <p
            className={cn(
              "font-semibold tabular-nums",
              remaining < 0 ? "text-red-600" : "",
            )}
          >
            {formatCents(remaining)}
          </p>
        </div>
      </div>
      <div className="mt-2 h-2 w-full bg-white/60 rounded-full overflow-hidden">
        <div
          className={cn(
            "h-full rounded-full transition-all",
            ratio > 1
              ? "bg-red-500"
              : ratio > 0.9
                ? "bg-amber-500"
                : "bg-emerald-500",
          )}
          style={{ width: `${Math.min(ratio * 100, 100)}%` }}
        />
      </div>
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
          ? "bg-sky-50 border-sky-200"
          : "bg-amber-50 border-amber-200",
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
            coversExpenses ? "text-sky-800" : "text-amber-800",
          )}>
            Income this month
          </span>
        </div>
        <div className="flex items-center gap-2">
          <span className={cn(
            "text-sm font-semibold tabular-nums",
            coversExpenses ? "text-sky-700" : "text-amber-700",
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
              className="flex items-center justify-between bg-white/60 rounded-md px-2.5 py-1.5 text-sm"
            >
              <span className="text-gray-700">{cat.category_name}</span>
              <span className="font-medium tabular-nums text-gray-900">
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

function BudgetRow({
  budget,
  catName,
  spent,
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
  spent: number;
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
  const pct = currentAmount > 0 ? (spent / currentAmount) * 100 : 0;
  const sliderMax = Math.max(
    currentAmount * 2,
    (historicalAvg ?? 0) * 2,
    spent * 1.5,
    50000,
  );
  const histPct =
    historicalAvg && sliderMax > 0
      ? (historicalAvg / sliderMax) * 100
      : null;

  return (
    <div
      className={cn(
        "bg-white rounded-lg border p-3",
        isEdited ? "border-sky-300 shadow-sm" : "border-gray-200",
      )}
    >
      <div className="flex items-start justify-between mb-2">
        <div className="flex items-center gap-2">
          <h3 className="font-medium text-sm">{catName}</h3>
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

      {/* Spent vs budget amounts */}
      <div className="flex justify-between text-xs text-gray-500 mb-1">
        <span>{formatCents(spent)} spent</span>
        <span className={cn("font-medium", isEdited ? "text-sky-600" : "text-gray-900")}>
          {formatCents(currentAmount)}
        </span>
      </div>

      {/* Progress bar with historical marker */}
      <div className="relative mb-2">
        <div className="w-full bg-gray-100 rounded-full h-2.5 overflow-hidden">
          <div
            className={cn(
              "h-full rounded-full transition-all",
              pct > 100 ? "bg-red-500" : pct > 80 ? "bg-amber-500" : "bg-sky-500",
            )}
            style={{ width: `${Math.min(pct, 100)}%` }}
          />
        </div>
        {histPct !== null && histPct <= 100 && (
          <div
            className="absolute top-0 h-2.5 w-0.5 bg-gray-400"
            style={{ left: `${histPct}%` }}
            title={`3-mo avg: ${formatCents(historicalAvg!)}`}
          />
        )}
      </div>

      {/* Slider */}
      <input
        type="range"
        min={0}
        max={sliderMax}
        step={500}
        value={currentAmount}
        onChange={(e) => onSliderChange(Number(e.target.value))}
        className="w-full h-1.5 accent-sky-500 cursor-pointer"
      />

      {/* Historical comparison */}
      <div className="flex justify-between text-[11px] text-gray-400 mt-0.5">
        <span>$0</span>
        {historicalAvg !== null && (
          <span>
            3-mo avg: {formatCents(historicalAvg)}
            {currentAmount < historicalAvg && (
              <span className="text-amber-500 ml-1">
                ({Math.round(((historicalAvg - currentAmount) / historicalAvg) * 100)}% below)
              </span>
            )}
          </span>
        )}
        <span>{formatCents(sliderMax)}</span>
      </div>
    </div>
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
    <div className="rounded-lg border border-amber-200 bg-amber-50/50 p-3 mb-1">
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-1.5">
          <Sparkles className="h-4 w-4 text-amber-500" />
          <span className="text-sm font-medium text-amber-800">
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
      <p className="text-xs text-amber-700 mb-2">
        Based on your last 3 months of spending:
      </p>
      <div className="space-y-1.5">
        {top.map((s) => (
          <div
            key={s.category_id}
            className="flex items-center justify-between bg-white rounded-md px-2.5 py-1.5 border border-amber-100"
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
