import { useCallback, useEffect, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import {
  ArrowDown,
  ArrowLeftRight,
  ArrowUp,
  ArrowUpDown,
  Check,
  ChevronLeft,
  ChevronRight,
  EyeOff,
  Eye,
  Plus,
  Search,
  Sparkles,
  Trash2,
  X,
} from "lucide-react";
import { Layout } from "../components/Layout";
import { SnapReceiptButton } from "../components/SnapReceiptButton";
import { receiptImageUrl } from "../hooks/useReceipts";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { Label } from "../components/ui/label";
import { Select } from "../components/ui/select";
import { Dialog, DialogTitle } from "../components/ui/dialog";
import { MoneyInput, formatCents } from "../components/MoneyInput";
import { MerchantCombobox } from "../components/MerchantCombobox";
import { SplitEditor } from "../components/SplitEditor";
import { useAccounts, useCreateAccount } from "../hooks/useAccounts";
import { useCategories } from "../hooks/useCategories";
import { useQueryClient } from "@tanstack/react-query";
import {
  useTransactions,
  useTransaction,
  useCreateTransaction,
  useDeleteTransaction,
  useReplaceLineItems,
  useUpdateTransaction,
  useCategorizeTransactions,
  useApplyCategories,
} from "../hooks/useTransactions";
import type { CategorizedTransaction } from "../hooks/useTransactions";
import { useDetectTransfers } from "../hooks/useTransfers";
import type {
  Merchant,
  LineItemInput,
} from "../types/models";
import { cn } from "../lib/utils";

function todayStr(): string {
  return new Date().toISOString().slice(0, 10);
}

function thirtyDaysAgoStr(): string {
  const d = new Date();
  d.setDate(d.getDate() - 30);
  return d.toISOString().slice(0, 10);
}

interface AddForm {
  date: string;
  account_id: number | null;
  merchant: Merchant | null;
  amount_cents: number;
  description: string;
  receipt_id: number | null;
}

const emptyAdd: AddForm = {
  date: todayStr(),
  account_id: null,
  merchant: null,
  amount_cents: 0,
  description: "",
  receipt_id: null,
};

type SortField = "posted_at" | "amount_cents" | "description" | "status" | "account_name" | "category_name";
type SortDir = "asc" | "desc";
type SortSpec = { field: SortField; dir: SortDir };

const DEFAULT_DIRS: Record<SortField, SortDir> = {
  posted_at: "desc",
  amount_cents: "desc",
  description: "asc",
  status: "asc",
  account_name: "asc",
  category_name: "asc",
};

export default function Transactions() {
  const [defaultDateFrom] = useState(thirtyDaysAgoStr);
  const [filters, setFilters] = useState<Record<string, string>>(() => ({
    date_from: new Date(thirtyDaysAgoStr()).toISOString(),
  }));
  const [searchOpen, setSearchOpen] = useState(false);
  const [dateFrom, setDateFrom] = useState(thirtyDaysAgoStr);
  const [dateTo, setDateTo] = useState("");
  const [filterAccount, setFilterAccount] = useState("");
  const [filterStatus, setFilterStatus] = useState("");
  const [filterCategory, setFilterCategory] = useState("");
  const [filterExcluded, setFilterExcluded] = useState("");
  const [page, setPage] = useState(0);
  const [sorts, setSorts] = useState<SortSpec[]>([{ field: "posted_at", dir: "desc" }]);
  const pageSize = 50;

  const sortParam = sorts.map((s) => `${s.field}:${s.dir}`).join(",");
  const queryParams: Record<string, string> = {
    ...filters,
    excluded: filters.excluded ?? "include",
    offset: String(page * pageSize),
    limit: String(pageSize),
    sort: sortParam,
  };
  const { data, isLoading } = useTransactions(queryParams);
  const { data: accounts = [] } = useAccounts();
  const { data: categories = [] } = useCategories();
  const createTxn = useCreateTransaction();
  const deleteTxn = useDeleteTransaction();
  const detectMut = useDetectTransfers();
  const categorizeMut = useCategorizeTransactions();

  const [addOpen, setAddOpen] = useState(false);
  const [addForm, setAddForm] = useState<AddForm>(emptyAdd);
  const [detectResult, setDetectResult] = useState<{ new_pairs: number; total_pairs: number } | null>(null);
  const [catReview, setCatReview] = useState<CategorizedTransaction[] | null>(null);
  const [catSkipped, setCatSkipped] = useState(0);

  const [selectedId, setSelectedId] = useState<number | null>(null);
  const lastKnownIdxRef = useRef(0);

  const [searchParams, setSearchParams] = useSearchParams();
  useEffect(() => {
    const open = searchParams.get("open");
    const manual = searchParams.get("manual");
    if (open) {
      setSelectedId(Number(open));
      searchParams.delete("open");
      setSearchParams(searchParams, { replace: true });
    } else if (manual) {
      setAddForm({
        ...emptyAdd,
        account_id: accounts.length === 1 ? accounts[0].id : null,
        receipt_id: Number(manual),
      });
      setAddOpen(true);
      searchParams.delete("manual");
      setSearchParams(searchParams, { replace: true });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchParams, accounts.length]);

  function applyFilters() {
    const f: Record<string, string> = {};
    if (dateFrom) f.date_from = new Date(dateFrom).toISOString();
    if (dateTo) f.date_to = new Date(dateTo + "T23:59:59").toISOString();
    if (filterAccount) f.account_id = filterAccount;
    if (filterStatus) f.status = filterStatus;
    if (filterCategory) f.category_id = filterCategory;
    if (filterExcluded) f.excluded = filterExcluded;
    setFilters(f);
    setPage(0);
    setSearchOpen(false);
  }

  function clearFilters() {
    const from = thirtyDaysAgoStr();
    setDateFrom(from);
    setDateTo("");
    setFilterAccount("");
    setFilterStatus("");
    setFilterCategory("");
    setFilterExcluded("");
    setFilters({ date_from: new Date(from).toISOString() });
    setPage(0);
  }

  function removeFilter(key: string) {
    const next = { ...filters };
    delete next[key];
    setFilters(next);
    if (key === "date_from") setDateFrom("");
    if (key === "date_to") setDateTo("");
    if (key === "account_id") setFilterAccount("");
    if (key === "status") setFilterStatus("");
    if (key === "category_id") setFilterCategory("");
    if (key === "excluded") setFilterExcluded("");
    setPage(0);
  }

  function toggleSort(field: SortField) {
    setSorts((prev) => {
      const idx = prev.findIndex((s) => s.field === field);
      if (idx === 0) {
        const toggled = { ...prev[0], dir: prev[0].dir === "asc" ? "desc" as SortDir : "asc" as SortDir };
        return [toggled, ...prev.slice(1)];
      }
      if (idx > 0) {
        const picked = prev[idx];
        return [{ ...picked, dir: picked.dir === "asc" ? "desc" as SortDir : "asc" as SortDir }, ...prev.filter((_, i) => i !== idx)];
      }
      const newSpec: SortSpec = { field, dir: DEFAULT_DIRS[field] };
      return [newSpec, ...prev].slice(0, 3);
    });
    setPage(0);
  }

  async function handleAdd(e: React.FormEvent) {
    e.preventDefault();
    if (!addForm.account_id || addForm.amount_cents <= 0) return;

    await createTxn.mutateAsync({
      account_id: addForm.account_id,
      merchant_id: addForm.merchant?.id ?? null,
      posted_at: new Date(addForm.date).toISOString(),
      amount_cents: addForm.amount_cents,
      description: addForm.description || null,
      receipt_id: addForm.receipt_id,
    });
    setAddOpen(false);
    setAddForm(emptyAdd);
  }

  async function handleDelete(id: number) {
    if (!confirm("Delete this transaction?")) return;
    await deleteTxn.mutateAsync(id);
  }

  function openAdd() {
    setAddForm({
      ...emptyAdd,
      account_id: accounts.length === 1 ? accounts[0].id : null,
    });
    setAddOpen(true);
  }

  const items = data?.items ?? [];
  const total = data?.total ?? 0;

  if (selectedId !== null) {
    const selectedIdx = items.findIndex((t) => t.id === selectedId);

    let prevId: number | null;
    let nextId: number | null;

    if (selectedIdx >= 0) {
      lastKnownIdxRef.current = selectedIdx;
      prevId = selectedIdx > 0 ? items[selectedIdx - 1].id : null;
      nextId =
        selectedIdx < items.length - 1 ? items[selectedIdx + 1].id : null;
    } else if (items.length > 0) {
      const idx = Math.min(lastKnownIdxRef.current, items.length - 1);
      prevId = idx > 0 ? items[idx - 1].id : null;
      nextId = items[idx].id;
    } else {
      prevId = null;
      nextId = null;
    }

    return (
      <TransactionDetailView
        key={selectedId}
        txnId={selectedId}
        onBack={() => setSelectedId(null)}
        onPrev={prevId !== null ? () => setSelectedId(prevId) : undefined}
        onNext={nextId !== null ? () => setSelectedId(nextId) : undefined}
      />
    );
  }
  const hasFilters = Object.keys(filters).length > 0;

  function filterLabel(key: string, value: string): string {
    if (key === "account_id") {
      const a = accounts.find((a) => String(a.id) === value);
      return a ? a.name : `Account #${value}`;
    }
    if (key === "category_id") {
      const c = categories.find((c) => String(c.id) === value);
      return c ? c.name : `Category #${value}`;
    }
    if (key === "status") return value;
    if (key === "excluded") return value === "only" ? "Excluded only" : value === "hide" ? "Hiding excluded" : "Including excluded";
    if (key === "date_from") return `From ${new Date(value).toLocaleDateString()}`;
    if (key === "date_to") return `To ${new Date(value).toLocaleDateString()}`;
    return `${key}: ${value}`;
  }

  return (
    <Layout>
      <div className="flex flex-wrap items-center justify-between gap-2 mb-3">
        <h1 className="text-xl font-bold text-gray-900 dark:text-gray-100">Transactions</h1>
        <div className="flex flex-wrap gap-2">
          <SnapReceiptButton label="" variant="outline" />
          <Button
            variant="outline"
            size="sm"
            title="Auto-categorize uncategorized transactions"
            disabled={categorizeMut.isPending}
            onClick={async () => {
              const r = await categorizeMut.mutateAsync({ limit: 200 });
              setCatReview(r.results);
              setCatSkipped(r.skipped);
            }}
          >
            <Sparkles className="h-4 w-4" />
            {categorizeMut.isPending ? " Categorizing…" : ""}
          </Button>
          <Button
            variant="outline"
            size="sm"
            title="Detect transfers"
            disabled={detectMut.isPending}
            onClick={async () => {
              const r = await detectMut.mutateAsync({});
              setDetectResult(r);
            }}
          >
            <ArrowLeftRight className="h-4 w-4" />
          </Button>
          <Button
            variant="outline"
            size="sm"
            onClick={() => setSearchOpen(true)}
            className={hasFilters ? "border-sky-500 text-sky-600" : ""}
          >
            <Search className="h-4 w-4" />
          </Button>
          <Button size="sm" onClick={openAdd}>
            <Plus className="h-4 w-4 mr-1" />
            Add
          </Button>
        </div>
      </div>

      {/* Active filter chips */}
      {hasFilters && (
        <div className="flex flex-wrap gap-1.5 mb-3">
          {Object.entries(filters).map(([key, value]) => (
            <span
              key={key}
              className="inline-flex items-center gap-1 rounded-full bg-sky-50 dark:bg-sky-900/30 border border-sky-200 dark:border-sky-800 px-2.5 py-0.5 text-xs text-sky-700 dark:text-sky-300"
            >
              {filterLabel(key, value)}
              <button
                onClick={() => removeFilter(key)}
                className="hover:text-sky-900"
              >
                <X className="h-3 w-3" />
              </button>
            </span>
          ))}
          <button
            onClick={clearFilters}
            className="text-xs text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-300 px-1"
          >
            Clear all
          </button>
        </div>
      )}

      {/* Transfer detection result */}
      {detectResult && (
        <div className="rounded-lg border border-sky-200 dark:border-sky-800 bg-sky-50 dark:bg-sky-900/30 p-2.5 mb-3 flex items-center justify-between">
          <p className="text-sm text-sky-800 dark:text-sky-300">
            {detectResult.new_pairs > 0
              ? `Found ${detectResult.new_pairs} new transfer pair${detectResult.new_pairs !== 1 ? "s" : ""} (${detectResult.total_pairs} total).`
              : `No new transfers found (${detectResult.total_pairs} existing).`}
          </p>
          <button onClick={() => setDetectResult(null)} className="text-sky-500 hover:text-sky-700">
            <X className="h-4 w-4" />
          </button>
        </div>
      )}

      {/* Categorization review modal */}
      {catReview !== null && (
        <CategorizationReviewModal
          results={catReview}
          skipped={catSkipped}
          onClose={() => setCatReview(null)}
        />
      )}

      {isLoading ? (
        <p className="text-gray-500 dark:text-gray-400 text-sm">Loading…</p>
      ) : items.length === 0 ? (
        <p className="text-gray-500 dark:text-gray-400 text-sm">
          No transactions{hasFilters ? " match your filters" : " yet"}.
        </p>
      ) : (
        <>
          <div className="text-xs text-gray-500 dark:text-gray-400 mb-2">
            {total.toLocaleString()} transactions
          </div>

          {/* Table */}
          <div className="overflow-x-auto min-w-0 rounded-lg border border-gray-200 dark:border-gray-700">
            <table className="w-full text-sm min-w-[600px]">
              <thead>
                <tr className="bg-gray-50 dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700">
                  <SortHeader field="posted_at" label="Date" sorts={sorts} onSort={toggleSort} />
                  <SortHeader field="description" label="Description" sorts={sorts} onSort={toggleSort} />
                  <SortHeader field="account_name" label="Account" sorts={sorts} onSort={toggleSort} />
                  <SortHeader field="category_name" label="Category" sorts={sorts} onSort={toggleSort} />
                  <SortHeader field="amount_cents" label="Amount" sorts={sorts} onSort={toggleSort} className="text-right" />
                  <SortHeader field="status" label="Status" sorts={sorts} onSort={toggleSort} />
                  <th className="px-2 py-2 w-8" />
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100 dark:divide-gray-700">
                {items.map((t) => (
                  <tr
                    key={t.id}
                    onClick={() => setSelectedId(t.id)}
                    className={cn(
                      "hover:bg-gray-50 dark:hover:bg-gray-800 cursor-pointer",
                      t.excluded
                        ? "bg-gray-50 dark:bg-gray-900/60 opacity-50"
                        : "bg-white dark:bg-gray-900",
                    )}
                  >
                    <td className="px-3 py-2 text-xs text-gray-600 dark:text-gray-400 whitespace-nowrap">
                      {new Date(t.posted_at).toLocaleDateString()}
                    </td>
                    <td className="px-3 py-2 max-w-[200px]">
                      {t.transfer_pair_id && t.transfer_account_name ? (
                        <>
                          <div className="truncate font-medium text-violet-700 dark:text-violet-400">
                            Transfer {t.amount_cents < 0 ? "→" : "←"} {t.transfer_account_name}
                          </div>
                          {t.description && (
                            <div className="truncate text-xs text-gray-400">{t.description}</div>
                          )}
                        </>
                      ) : (
                        <>
                          <div className="truncate font-medium text-gray-900 dark:text-gray-100">
                            {t.merchant_name || t.description || "—"}
                          </div>
                          {t.merchant_name && t.description && t.merchant_name !== t.description && (
                            <div className="truncate text-xs text-gray-400">{t.description}</div>
                          )}
                        </>
                      )}
                    </td>
                    <td className="px-3 py-2 text-xs text-gray-600 dark:text-gray-400 whitespace-nowrap">
                      {t.account_name ?? "—"}
                    </td>
                    <td className="px-3 py-2 text-xs whitespace-nowrap">
                      {t.category_name ? (
                        <span className={cn(
                          t.needs_review && t.category_source !== "user" && t.category_source !== "qif_import"
                            ? "text-amber-600"
                            : "text-gray-600"
                        )}>
                          {t.category_name}
                          {t.needs_review && t.category_source !== "user" && t.category_source !== "qif_import" && (
                            <span className="ml-1 text-[10px]" title={`Auto-categorized (${t.category_source}, ${Math.round((t.category_confidence ?? 0) * 100)}% confidence)`}>?</span>
                          )}
                        </span>
                      ) : (
                        <span className="text-gray-400">—</span>
                      )}
                    </td>
                    <td className={cn(
                      "px-3 py-2 text-right font-semibold tabular-nums whitespace-nowrap",
                      t.amount_cents > 0
                        ? "text-emerald-600 dark:text-emerald-400"
                        : "text-gray-900 dark:text-gray-100",
                    )}>
                      {formatCents(t.amount_cents)}
                    </td>
                    <td className="px-3 py-2">
                      <div className="flex items-center gap-1">
                        <span
                          className={cn(
                            "inline-block rounded px-1.5 py-0.5 text-[10px] font-medium",
                            t.status === "confirmed"
                              ? "bg-emerald-100 dark:bg-emerald-900/40 text-emerald-700 dark:text-emerald-300"
                              : t.status === "split"
                                ? "bg-green-100 dark:bg-green-900/40 text-green-700 dark:text-green-300"
                                : t.status === "final"
                                  ? "bg-sky-100 dark:bg-sky-900/40 text-sky-700 dark:text-sky-300"
                                  : "bg-gray-100 dark:bg-gray-700 text-gray-600 dark:text-gray-400"
                          )}
                        >
                          {t.status}
                        </span>
                        {t.transfer_pair_id && (
                          <span
                            className="inline-block rounded px-1.5 py-0.5 text-[10px] font-medium bg-violet-100 dark:bg-violet-900/40 text-violet-700 dark:text-violet-300"
                            title={`Matched transfer pair #${t.transfer_pair_id} (detected via Detect Transfers)`}
                          >
                            xfer
                          </span>
                        )}
                        {t.excluded && (
                          <span
                            className="inline-block rounded px-1.5 py-0.5 text-[10px] font-medium bg-orange-100 dark:bg-orange-900/40 text-orange-700 dark:text-orange-300"
                            title="Excluded from budget calculations"
                          >
                            excluded
                          </span>
                        )}
                      </div>
                    </td>
                    <td className="px-2 py-2">
                      <button
                        onClick={(e) => {
                          e.stopPropagation();
                          handleDelete(t.id);
                        }}
                        className="p-1 text-gray-300 hover:text-red-500"
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {total > pageSize && (
            <div className="flex items-center justify-between mt-4">
              <Button
                variant="outline"
                size="sm"
                disabled={page === 0}
                onClick={() => setPage(page - 1)}
              >
                Prev
              </Button>
              <span className="text-xs text-gray-500 dark:text-gray-400">
                {page * pageSize + 1}–{Math.min((page + 1) * pageSize, total)}{" "}
                of {total.toLocaleString()}
              </span>
              <Button
                variant="outline"
                size="sm"
                disabled={(page + 1) * pageSize >= total}
                onClick={() => setPage(page + 1)}
              >
                Next
              </Button>
            </div>
          )}
        </>
      )}

      {/* Filter dialog */}
      <Dialog open={searchOpen} onClose={() => setSearchOpen(false)}>
        <DialogTitle>Filter Transactions</DialogTitle>
        <div className="space-y-3">
          <div className="flex items-end gap-2">
            <div className="flex-1">
              <Label>From</Label>
              <input
                type="date"
                value={dateFrom}
                onChange={(e) => setDateFrom(e.target.value)}
                className="flex h-10 w-full rounded-md border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-800 px-3 py-2 text-sm text-gray-900 dark:text-gray-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-500"
              />
            </div>
            <div className="flex-1">
              <Label>To</Label>
              <input
                type="date"
                value={dateTo}
                onChange={(e) => setDateTo(e.target.value)}
                className="flex h-10 w-full rounded-md border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-800 px-3 py-2 text-sm text-gray-900 dark:text-gray-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-500"
              />
            </div>
          </div>
          <div className="flex gap-2">
            <Button
              variant="outline"
              size="sm"
              onClick={() => {
                setDateFrom(defaultDateFrom);
                setDateTo("");
              }}
              className={dateFrom === defaultDateFrom && !dateTo ? "border-sky-500 text-sky-600" : ""}
            >
              Last 30 Days
            </Button>
            <Button
              variant="outline"
              size="sm"
              onClick={() => {
                setDateFrom("");
                setDateTo("");
              }}
              className={!dateFrom && !dateTo ? "border-sky-500 text-sky-600" : ""}
            >
              All Time
            </Button>
          </div>
          {accounts.length > 0 && (
            <div>
              <Label>Account</Label>
              <Select
                value={filterAccount}
                onChange={(e) => setFilterAccount(e.target.value)}
              >
                <option value="">All accounts</option>
                {accounts.map((a) => (
                  <option key={a.id} value={a.id}>
                    {a.name}
                  </option>
                ))}
              </Select>
            </div>
          )}
          {categories.length > 0 && (
            <div>
              <Label>Category</Label>
              <Select
                value={filterCategory}
                onChange={(e) => setFilterCategory(e.target.value)}
              >
                <option value="">All categories</option>
                {categories
                  .slice()
                  .sort((a, b) => a.name.localeCompare(b.name))
                  .map((c) => (
                    <option key={c.id} value={c.id}>
                      {c.name}
                    </option>
                  ))}
              </Select>
            </div>
          )}
          <div>
            <Label>Status</Label>
            <Select
              value={filterStatus}
              onChange={(e) => setFilterStatus(e.target.value)}
            >
              <option value="">All</option>
              <option value="pending">Pending</option>
              <option value="confirmed">Confirmed</option>
              <option value="split">Split</option>
              <option value="final">Final</option>
            </Select>
          </div>
          <div>
            <Label>Excluded</Label>
            <Select
              value={filterExcluded}
              onChange={(e) => setFilterExcluded(e.target.value)}
            >
              <option value="">All</option>
              <option value="hide">Hide excluded</option>
              <option value="only">Excluded only</option>
            </Select>
          </div>
          <div>
            <Label>Sort (up to 3)</Label>
            <SortBuilder sorts={sorts} onChange={(s) => { setSorts(s); setPage(0); }} />
          </div>
          <div className="flex justify-end gap-2 pt-2">
            <Button
              variant="outline"
              onClick={() => {
                clearFilters();
                setSorts([{ field: "posted_at", dir: "desc" }]);
                setSearchOpen(false);
              }}
            >
              Clear
            </Button>
            <Button onClick={applyFilters}>Apply</Button>
          </div>
        </div>
      </Dialog>

      {/* Add transaction dialog */}
      <Dialog open={addOpen} onClose={() => setAddOpen(false)}>
        <DialogTitle>
          {addForm.receipt_id ? "Add Transaction (manual fallback)" : "Add Transaction"}
        </DialogTitle>
        <form onSubmit={handleAdd} className="space-y-4">
          {addForm.receipt_id && (
            <div className="rounded-lg border border-gray-200 dark:border-gray-700 p-2 bg-gray-50 dark:bg-gray-700">
              <p className="text-xs text-gray-500 dark:text-gray-400 mb-1">Attached receipt</p>
              <img
                src={receiptImageUrl(addForm.receipt_id)}
                alt="Receipt"
                className="max-h-40 mx-auto rounded"
              />
            </div>
          )}
          <div>
            <Label>Date</Label>
            <input
              type="date"
              value={addForm.date}
              onChange={(e) =>
                setAddForm({ ...addForm, date: e.target.value })
              }
              className="flex h-10 w-full rounded-md border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-800 px-3 py-2 text-sm text-gray-900 dark:text-gray-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-500"
            />
          </div>
          <div>
            <Label>Account</Label>
            {accounts.length === 0 ? (
              <QuickAccountCreator
                onCreated={(id) =>
                  setAddForm({ ...addForm, account_id: id })
                }
              />
            ) : (
              <Select
                value={addForm.account_id ?? ""}
                onChange={(e) =>
                  setAddForm({
                    ...addForm,
                    account_id: e.target.value ? Number(e.target.value) : null,
                  })
                }
              >
                <option value="" disabled>
                  Select account…
                </option>
                {accounts.map((a) => (
                  <option key={a.id} value={a.id}>
                    {a.name}
                  </option>
                ))}
              </Select>
            )}
          </div>
          <div>
            <Label>Merchant</Label>
            <MerchantCombobox
              value={addForm.merchant}
              onSelect={(m) => setAddForm({ ...addForm, merchant: m })}
            />
          </div>
          <div>
            <Label>Amount</Label>
            <MoneyInput
              valueCents={addForm.amount_cents}
              onValueChange={(cents) =>
                setAddForm({ ...addForm, amount_cents: cents })
              }
            />
          </div>
          <div>
            <Label>Description</Label>
            <Input
              value={addForm.description}
              onChange={(e) =>
                setAddForm({ ...addForm, description: e.target.value })
              }
              placeholder="Optional"
            />
          </div>
          <div className="flex justify-end gap-2 pt-2">
            <Button
              type="button"
              variant="outline"
              onClick={() => setAddOpen(false)}
            >
              Cancel
            </Button>
            <Button
              type="submit"
              disabled={
                !addForm.account_id ||
                addForm.amount_cents <= 0 ||
                createTxn.isPending
              }
            >
              Save
            </Button>
          </div>
        </form>
      </Dialog>
    </Layout>
  );
}

const TIER_LABELS: Record<string, string> = {
  exact: "Exact match",
  substring: "Substring",
  embedding: "Embedding",
  llm: "LLM",
  merchant_default: "Merchant default",
  none: "None",
};

function CategorizationReviewModal({
  results,
  skipped,
  onClose,
}: {
  results: CategorizedTransaction[];
  skipped: number;
  onClose: () => void;
}) {
  const [checked, setChecked] = useState<Set<number>>(() => {
    const initial = new Set<number>();
    for (const r of results) {
      if (r.category_id !== null && r.confidence >= 0.70) {
        initial.add(r.transaction_id);
      }
    }
    return initial;
  });

  const applyMut = useApplyCategories();
  const [applied, setApplied] = useState(false);
  const [applyResult, setApplyResult] = useState<{ applied: number; rules_created: number } | null>(null);

  const toggle = useCallback((id: number) => {
    setChecked((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }, []);

  const selectAll = useCallback(() => {
    setChecked(new Set(results.filter((r) => r.category_id !== null).map((r) => r.transaction_id)));
  }, [results]);

  const selectNone = useCallback(() => {
    setChecked(new Set());
  }, []);

  async function handleApply() {
    const items = results
      .filter((r) => checked.has(r.transaction_id) && r.category_id !== null)
      .map((r) => ({ transaction_id: r.transaction_id, category_id: r.category_id! }));
    if (items.length === 0) return;
    const res = await applyMut.mutateAsync(items);
    setApplyResult(res);
    setApplied(true);
  }

  const categorizable = results.filter((r) => r.category_id !== null);

  return (
    <Dialog open onClose={onClose} className="max-w-2xl">
      <DialogTitle>Review Auto-Categorization</DialogTitle>

      {applied && applyResult ? (
        <div className="space-y-3">
          <div className="rounded-lg border border-green-200 dark:border-green-800 bg-green-50 dark:bg-green-900/30 p-3">
            <p className="text-sm text-green-800 dark:text-green-300">
              Applied {applyResult.applied} categor{applyResult.applied !== 1 ? "ies" : "y"}.
              {applyResult.rules_created > 0 &&
                ` Created ${applyResult.rules_created} new rule${applyResult.rules_created !== 1 ? "s" : ""} for future matching.`}
            </p>
          </div>
          <div className="flex justify-end">
            <Button onClick={onClose}>Done</Button>
          </div>
        </div>
      ) : (
        <div className="space-y-3">
          {categorizable.length === 0 ? (
            <p className="text-sm text-gray-500">
              No categorization suggestions found
              {skipped > 0 && ` (${skipped} transaction${skipped !== 1 ? "s" : ""} had no description or could not be matched)`}.
            </p>
          ) : (
            <>
              <div className="flex items-center justify-between text-xs text-gray-500">
                <span>
                  {categorizable.length} suggestion{categorizable.length !== 1 ? "s" : ""}
                  {skipped > 0 && `, ${skipped} skipped`}
                </span>
                <span className="flex gap-2">
                  <button onClick={selectAll} className="text-sky-600 hover:text-sky-800">All</button>
                  <button onClick={selectNone} className="text-sky-600 hover:text-sky-800">None</button>
                </span>
              </div>

              <div className="max-h-[50vh] overflow-y-auto divide-y divide-gray-100 dark:divide-gray-700 border border-gray-200 dark:border-gray-700 rounded-lg">
                {categorizable.map((r) => (
                  <label
                    key={r.transaction_id}
                    className={cn(
                      "flex items-start gap-3 px-3 py-2.5 cursor-pointer hover:bg-gray-50 dark:hover:bg-gray-700",
                      checked.has(r.transaction_id) && "bg-sky-50/50 dark:bg-sky-900/30",
                    )}
                  >
                    <div className="pt-0.5">
                      <div
                        className={cn(
                          "h-4 w-4 rounded border flex items-center justify-center",
                          checked.has(r.transaction_id)
                            ? "bg-sky-500 border-sky-500 text-white"
                            : "border-gray-300",
                        )}
                      >
                        {checked.has(r.transaction_id) && <Check className="h-3 w-3" />}
                      </div>
                      <input
                        type="checkbox"
                        className="sr-only"
                        checked={checked.has(r.transaction_id)}
                        onChange={() => toggle(r.transaction_id)}
                      />
                    </div>

                    <div className="flex-1 min-w-0">
                      <div className="flex items-baseline justify-between gap-2">
                        <span className="text-sm font-medium text-gray-900 dark:text-gray-100 truncate">
                          {r.description || `Transaction #${r.transaction_id}`}
                        </span>
                        <span className="text-xs text-gray-500 dark:text-gray-400 tabular-nums whitespace-nowrap">
                          {formatCents(r.amount_cents)}
                        </span>
                      </div>
                      <div className="flex items-center gap-2 mt-0.5">
                        {r.current_category_name && (
                          <>
                            <span className="text-xs text-gray-400">{r.current_category_name}</span>
                            <span className="text-xs text-gray-300">→</span>
                          </>
                        )}
                        <span className="text-xs font-medium text-sky-700 dark:text-sky-300">{r.category_name}</span>
                      </div>
                      <div className="flex items-center gap-1.5 mt-0.5">
                        <span
                          className={cn(
                            "inline-block rounded px-1.5 py-0.5 text-[10px] font-medium",
                            r.tier === "exact"
                              ? "bg-green-100 dark:bg-green-900/40 text-green-700 dark:text-green-300"
                              : r.tier === "substring"
                                ? "bg-emerald-100 dark:bg-emerald-900/40 text-emerald-700 dark:text-emerald-300"
                                : r.tier === "embedding"
                                  ? "bg-blue-100 dark:bg-blue-900/40 text-blue-700 dark:text-blue-300"
                                  : r.tier === "llm"
                                    ? "bg-purple-100 dark:bg-purple-900/40 text-purple-700 dark:text-purple-300"
                                    : "bg-gray-100 dark:bg-gray-700 text-gray-600 dark:text-gray-400",
                          )}
                        >
                          {TIER_LABELS[r.tier] || r.tier}
                        </span>
                        <span className="text-[10px] text-gray-400">
                          {Math.round(r.confidence * 100)}%
                        </span>
                        {r.merchant_guess && (
                          <span className="text-[10px] text-gray-400 truncate">
                            ({r.merchant_guess})
                          </span>
                        )}
                      </div>
                    </div>
                  </label>
                ))}
              </div>
            </>
          )}

          <div className="flex justify-end gap-2 pt-1">
            <Button variant="outline" onClick={onClose}>
              Cancel
            </Button>
            {categorizable.length > 0 && (
              <Button
                onClick={handleApply}
                disabled={checked.size === 0 || applyMut.isPending}
              >
                {applyMut.isPending
                  ? "Applying…"
                  : `Apply ${checked.size} Selected`}
              </Button>
            )}
          </div>
        </div>
      )}
    </Dialog>
  );
}

const SORT_FIELD_LABELS: Record<SortField, string> = {
  posted_at: "Date",
  amount_cents: "Amount",
  description: "Description",
  status: "Status",
  account_name: "Account",
  category_name: "Category",
};

function SortBuilder({
  sorts,
  onChange,
}: {
  sorts: SortSpec[];
  onChange: (s: SortSpec[]) => void;
}) {
  function updateField(idx: number, field: SortField) {
    const next = sorts.map((s, i) =>
      i === idx ? { field, dir: DEFAULT_DIRS[field] } : s,
    );
    onChange(next);
  }

  function updateDir(idx: number, dir: SortDir) {
    onChange(sorts.map((s, i) => (i === idx ? { ...s, dir } : s)));
  }

  function removeSort(idx: number) {
    const next = sorts.filter((_, i) => i !== idx);
    onChange(next.length ? next : [{ field: "posted_at", dir: "desc" }]);
  }

  function addSort() {
    const used = new Set(sorts.map((s) => s.field));
    const available = (Object.keys(SORT_FIELD_LABELS) as SortField[]).find(
      (f) => !used.has(f),
    );
    if (available && sorts.length < 3) {
      onChange([...sorts, { field: available, dir: DEFAULT_DIRS[available] }]);
    }
  }

  const usedFields = new Set(sorts.map((s) => s.field));

  return (
    <div className="space-y-1.5">
      {sorts.map((s, idx) => (
        <div key={idx} className="flex gap-1.5 items-center">
          <span className="text-[10px] text-gray-400 w-4">{idx + 1}.</span>
          <select
            className="flex-1 h-8 rounded-md border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100 px-2 text-xs"
            value={s.field}
            onChange={(e) => updateField(idx, e.target.value as SortField)}
          >
            {(Object.keys(SORT_FIELD_LABELS) as SortField[]).map((f) => (
              <option key={f} value={f} disabled={usedFields.has(f) && f !== s.field}>
                {SORT_FIELD_LABELS[f]}
              </option>
            ))}
          </select>
          <select
            className="w-16 h-8 rounded-md border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100 px-1 text-xs"
            value={s.dir}
            onChange={(e) => updateDir(idx, e.target.value as SortDir)}
          >
            <option value="asc">A→Z</option>
            <option value="desc">Z→A</option>
          </select>
          {sorts.length > 1 && (
            <button onClick={() => removeSort(idx)} className="text-gray-400 hover:text-red-500">
              <X className="h-3.5 w-3.5" />
            </button>
          )}
        </div>
      ))}
      {sorts.length < 3 && (
        <button
          onClick={addSort}
          className="text-xs text-sky-600 hover:text-sky-800 font-medium"
        >
          + Add sort level
        </button>
      )}
    </div>
  );
}

function SortHeader({
  field,
  label,
  sorts,
  onSort,
  className,
}: {
  field: SortField;
  label: string;
  sorts: SortSpec[];
  onSort: (f: SortField) => void;
  className?: string;
}) {
  const idx = sorts.findIndex((s) => s.field === field);
  const active = idx >= 0;
  const dir = active ? sorts[idx].dir : null;
  const rank = active && sorts.length > 1 ? idx + 1 : null;

  return (
    <th
      className={cn(
        "px-3 py-2 font-medium text-xs cursor-pointer select-none hover:text-gray-900 dark:hover:text-gray-200 whitespace-nowrap",
        active ? "text-gray-900 dark:text-gray-100" : "text-gray-600 dark:text-gray-400",
        className,
      )}
      onClick={() => onSort(field)}
    >
      <span className="inline-flex items-center gap-1">
        {label}
        {active ? (
          <>
            {dir === "asc" ? <ArrowUp className="h-3 w-3" /> : <ArrowDown className="h-3 w-3" />}
            {rank && <span className="text-[9px] text-sky-500 font-bold -ml-0.5">{rank}</span>}
          </>
        ) : (
          <ArrowUpDown className="h-3 w-3 opacity-30" />
        )}
      </span>
    </th>
  );
}

function QuickAccountCreator({
  onCreated,
}: {
  onCreated: (id: number) => void;
}) {
  const [name, setName] = useState("");
  const createAcct = useCreateAccount();

  async function handleCreate() {
    if (!name.trim()) return;
    const a = await createAcct.mutateAsync({
      name: name.trim(),
      type: "checking",
    });
    onCreated(a.id);
  }

  return (
    <div className="flex gap-2">
      <Input
        value={name}
        onChange={(e) => setName(e.target.value)}
        placeholder="Account name"
        className="flex-1"
      />
      <Button
        type="button"
        size="sm"
        onClick={handleCreate}
        disabled={!name.trim() || createAcct.isPending}
      >
        Create
      </Button>
    </div>
  );
}

function TransactionDetailView({
  txnId,
  onBack,
  onPrev,
  onNext,
}: {
  txnId: number;
  onBack: () => void;
  onPrev?: () => void;
  onNext?: () => void;
}) {
  const qc = useQueryClient();
  const { data: txn, isLoading } = useTransaction(txnId);
  const replaceMut = useReplaceLineItems();
  const updateMut = useUpdateTransaction();

  const [splits, setSplits] = useState<LineItemInput[] | null>(null);
  const [dirty, setDirty] = useState(false);

  async function handleToggleExcluded(exclude: boolean) {
    await updateMut.mutateAsync({ id: txnId, excluded: exclude ? true : null });
    await qc.invalidateQueries({ queryKey: ["transactions", txnId] });
  }

  const currentSplits =
    splits ??
    txn?.line_items.map((li) => ({
      category_id: li.category_id,
      description: li.description,
      amount_cents: li.amount_cents,
    })) ??
    [];

  function handleChange(items: LineItemInput[]) {
    setSplits(items);
    setDirty(true);
  }

  async function handleSave() {
    if (!txn || !splits) return;
    await replaceMut.mutateAsync({
      txnId: txn.id,
      line_items: splits,
    });
    if (txn.status !== "confirmed") {
      await updateMut.mutateAsync({ id: txn.id, status: "confirmed" });
    }
    setDirty(false);
    setSplits(null);
  }

  async function handleConfirm() {
    if (!txn) return;
    if (dirty && splits) {
      await replaceMut.mutateAsync({
        txnId: txn.id,
        line_items: splits,
      });
      setSplits(null);
      setDirty(false);
    }
    await updateMut.mutateAsync({ id: txn.id, status: "confirmed" });
  }

  const prefilled =
    txn &&
    txn.line_items.length === 1 &&
    txn.line_items[0].category_name === "Uncategorized" &&
    txn.merchant_id;

  if (isLoading || !txn) {
    return (
      <Layout>
        <div className="flex items-center justify-between mb-4">
          <button onClick={onBack} className="flex items-center text-sm text-sky-600 dark:text-sky-400">
            <ChevronLeft className="h-4 w-4" />
            Back
          </button>
          <div className="flex gap-1">
            <button
              disabled={!onPrev}
              className="p-1.5 rounded-md border border-gray-200 text-gray-300 cursor-not-allowed"
            >
              <ChevronLeft className="h-4 w-4" />
            </button>
            <button
              disabled={!onNext}
              className="p-1.5 rounded-md border border-gray-200 text-gray-300 cursor-not-allowed"
            >
              <ChevronRight className="h-4 w-4" />
            </button>
          </div>
        </div>
        <p className="text-gray-500 dark:text-gray-400 text-sm">Loading…</p>
      </Layout>
    );
  }

  const allocated = currentSplits.reduce((s, i) => s + i.amount_cents, 0);
  const balanced = allocated === txn.amount_cents;
  const validCategories = currentSplits.every((s) => s.category_id > 0);

  return (
    <Layout>
      <div className="flex items-center justify-between mb-4">
        <button
          onClick={onBack}
          className="flex items-center text-sm text-sky-600 dark:text-sky-400"
        >
          <ChevronLeft className="h-4 w-4" />
          Back
        </button>
        <div className="flex gap-1">
          <button
            onClick={onPrev}
            disabled={!onPrev}
            className={cn(
              "p-1.5 rounded-md border",
              onPrev
                ? "border-gray-300 dark:border-gray-600 text-gray-600 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-700"
                : "border-gray-200 dark:border-gray-700 text-gray-300 dark:text-gray-600 cursor-not-allowed",
            )}
            title="Previous transaction"
          >
            <ChevronLeft className="h-4 w-4" />
          </button>
          <button
            onClick={onNext}
            disabled={!onNext}
            className={cn(
              "p-1.5 rounded-md border",
              onNext
                ? "border-gray-300 dark:border-gray-600 text-gray-600 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-700"
                : "border-gray-200 dark:border-gray-700 text-gray-300 dark:text-gray-600 cursor-not-allowed",
            )}
            title="Next transaction"
          >
            <ChevronRight className="h-4 w-4" />
          </button>
        </div>
      </div>

      {txn.excluded && (
        <div className="rounded-lg border border-orange-200 dark:border-orange-800 bg-orange-50 dark:bg-orange-900/30 p-2.5 mb-3 flex items-center justify-between">
          <p className="text-sm text-orange-800 dark:text-orange-300">
            This transaction is excluded from budget calculations.
          </p>
          <Button
            variant="outline"
            size="sm"
            onClick={() => handleToggleExcluded(false)}
            disabled={updateMut.isPending}
          >
            <Eye className="h-3.5 w-3.5 mr-1" />
            Include
          </Button>
        </div>
      )}

      <div className={cn(
        "bg-white dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700 p-4 mb-4",
        txn.excluded && "opacity-50",
      )}>
        <div className="flex justify-between items-start">
          <div>
            <h2 className="font-semibold text-gray-900 dark:text-gray-100">
              {txn.merchant_name || txn.description || "Transaction"}
            </h2>
            <p className="text-xs text-gray-500 dark:text-gray-400">
              {new Date(txn.posted_at).toLocaleDateString()}
              {txn.account_name && (
                <span className="ml-2 inline-flex items-center rounded bg-gray-100 dark:bg-gray-700 px-1.5 py-0.5 text-gray-600 dark:text-gray-400">
                  {txn.account_name}
                </span>
              )}
            </p>
          </div>
          <span className="text-lg font-bold text-gray-900 dark:text-gray-100">
            {formatCents(txn.amount_cents)}
          </span>
        </div>
        {txn.description && txn.merchant_name && (
          <p className="text-sm text-gray-600 dark:text-gray-400 mt-1">{txn.description}</p>
        )}
        {txn.receipt_id && (
          <img
            src={receiptImageUrl(txn.receipt_id)}
            alt="Receipt"
            className="mt-3 max-h-40 mx-auto rounded border border-gray-200 dark:border-gray-700"
          />
        )}
      </div>

      <h3 className="text-sm font-semibold mb-2 text-gray-900 dark:text-gray-100">Line Items</h3>

      {prefilled && !dirty && (
        <p className="text-xs text-amber-600 mb-2">
          This transaction is uncategorized. Add splits or pick a category
          below.
        </p>
      )}

      <SplitEditor
        totalCents={txn.amount_cents}
        items={currentSplits}
        onChange={handleChange}
      />

      <div className="mt-4 flex gap-2">
        <Button
          onClick={handleSave}
          disabled={!dirty || !balanced || !validCategories || replaceMut.isPending || updateMut.isPending}
          className="flex-1"
        >
          {replaceMut.isPending
            ? "Saving…"
            : currentSplits.length > 1
              ? "Save Splits"
              : "Save"}
        </Button>

        {txn.status === "confirmed" ? (
          <span className="inline-flex items-center rounded-md bg-emerald-100 dark:bg-emerald-900/40 text-emerald-700 dark:text-emerald-300 px-3 py-2">
            <Check className="h-4 w-4" />
          </span>
        ) : (
          <Button
            onClick={handleConfirm}
            disabled={updateMut.isPending || replaceMut.isPending || (dirty && (!balanced || !validCategories))}
            variant="outline"
          >
            <Check className="h-4 w-4 mr-1" />
            {updateMut.isPending || replaceMut.isPending ? "…" : "Confirm"}
          </Button>
        )}
        {!txn.excluded && (
          <Button
            variant="outline"
            onClick={() => handleToggleExcluded(true)}
            disabled={updateMut.isPending}
            title="Exclude from budget calculations"
          >
            <EyeOff className="h-4 w-4" />
          </Button>
        )}
      </div>
    </Layout>
  );
}
