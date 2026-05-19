import { useState } from "react";
import { Pencil, Plus, Trash2 } from "lucide-react";
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
  useUpdateBudget,
} from "../hooks/useBudgets";
import { useCategories } from "../hooks/useCategories";
import type { Budget } from "../types/models";
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

export default function Budgets() {
  const { data: budgets = [], isLoading } = useBudgets();
  const { data: status = [] } = useBudgetStatus();
  const { data: categories = [] } = useCategories();
  const createMut = useCreateBudget();
  const updateMut = useUpdateBudget();
  const deleteMut = useDeleteBudget();

  const [modalOpen, setModalOpen] = useState(false);
  const [form, setForm] = useState<FormState>(emptyForm);

  const catMap = new Map(categories.map((c) => [c.id, c.name]));
  const statusMap = new Map(status.map((s) => [s.category_id, s]));

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

  return (
    <Layout>
      <div className="flex items-center justify-between mb-4">
        <h1 className="text-xl font-bold">Budgets</h1>
        <Button size="sm" onClick={openCreate}>
          <Plus className="h-4 w-4 mr-1" />
          Add
        </Button>
      </div>

      {isLoading ? (
        <p className="text-gray-500 text-sm">Loading…</p>
      ) : budgets.length === 0 ? (
        <p className="text-gray-500 text-sm">
          No budgets yet. Tap Add to create one.
        </p>
      ) : (
        <div className="space-y-3">
          {budgets.map((b) => {
            const catName = catMap.get(b.category_id) ?? "Unknown";
            const st = statusMap.get(b.category_id);
            const pct = st?.percent_used ?? 0;

            return (
              <div
                key={b.id}
                className="bg-white rounded-lg border border-gray-200 p-4"
              >
                <div className="flex items-start justify-between mb-2">
                  <div>
                    <h3 className="font-medium text-sm">{catName}</h3>
                    <p className="text-xs text-gray-500 capitalize">
                      {b.period}
                    </p>
                  </div>
                  <div className="flex gap-1">
                    <Button
                      variant="ghost"
                      size="icon"
                      className="h-7 w-7"
                      onClick={() => openEdit(b)}
                    >
                      <Pencil className="h-3.5 w-3.5" />
                    </Button>
                    <Button
                      variant="ghost"
                      size="icon"
                      className="h-7 w-7 text-red-500"
                      onClick={() => handleDelete(b.id)}
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                    </Button>
                  </div>
                </div>

                <div className="flex justify-between text-sm mb-1">
                  <span>
                    {st ? formatCents(st.spent_cents) : "$0.00"} spent
                  </span>
                  <span className="font-medium">
                    {formatCents(b.amount_cents)}
                  </span>
                </div>

                <div className="w-full bg-gray-100 rounded-full h-2.5 overflow-hidden">
                  <div
                    className={cn(
                      "h-full rounded-full transition-all",
                      pct > 100
                        ? "bg-red-500"
                        : pct > 80
                          ? "bg-amber-500"
                          : "bg-sky-500",
                    )}
                    style={{ width: `${Math.min(pct, 100)}%` }}
                  />
                </div>

                {st && (
                  <p className="text-xs text-gray-500 mt-1">
                    {formatCents(st.remaining_cents)} remaining ({pct.toFixed(0)}
                    %)
                  </p>
                )}
              </div>
            );
          })}
        </div>
      )}

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
