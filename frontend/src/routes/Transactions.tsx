import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import {
  ArrowDown,
  ArrowLeftRight,
  ArrowUp,
  ArrowUpDown,
  ChevronLeft,
  Plus,
  Search,
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
import {
  useTransactions,
  useTransaction,
  useCreateTransaction,
  useDeleteTransaction,
  useReplaceLineItems,
} from "../hooks/useTransactions";
import { useDetectTransfers } from "../hooks/useTransfers";
import type {
  Merchant,
  LineItemInput,
} from "../types/models";
import { cn } from "../lib/utils";

function todayStr(): string {
  return new Date().toISOString().slice(0, 10);
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

type SortField = "posted_at" | "amount_cents" | "description" | "status";
type SortDir = "asc" | "desc";

export default function Transactions() {
  const [filters, setFilters] = useState<Record<string, string>>({});
  const [searchOpen, setSearchOpen] = useState(false);
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [filterAccount, setFilterAccount] = useState("");
  const [filterStatus, setFilterStatus] = useState("");
  const [page, setPage] = useState(0);
  const [sortBy, setSortBy] = useState<SortField>("posted_at");
  const [sortDir, setSortDir] = useState<SortDir>("desc");
  const pageSize = 50;

  const queryParams: Record<string, string> = {
    ...filters,
    offset: String(page * pageSize),
    limit: String(pageSize),
    sort_by: sortBy,
    sort_dir: sortDir,
  };
  const { data, isLoading } = useTransactions(queryParams);
  const { data: accounts = [] } = useAccounts();
  const createTxn = useCreateTransaction();
  const deleteTxn = useDeleteTransaction();
  const detectMut = useDetectTransfers();

  const [addOpen, setAddOpen] = useState(false);
  const [addForm, setAddForm] = useState<AddForm>(emptyAdd);
  const [detectResult, setDetectResult] = useState<{ new_pairs: number; total_pairs: number } | null>(null);

  const [selectedId, setSelectedId] = useState<number | null>(null);

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
    setFilters(f);
    setPage(0);
    setSearchOpen(false);
  }

  function clearFilters() {
    setDateFrom("");
    setDateTo("");
    setFilterAccount("");
    setFilterStatus("");
    setFilters({});
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
    setPage(0);
  }

  function toggleSort(field: SortField) {
    if (sortBy === field) {
      setSortDir(sortDir === "asc" ? "desc" : "asc");
    } else {
      setSortBy(field);
      setSortDir(field === "amount_cents" ? "desc" : "asc");
    }
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

  if (selectedId !== null) {
    return (
      <TransactionDetailView
        txnId={selectedId}
        onBack={() => setSelectedId(null)}
      />
    );
  }

  const items = data?.items ?? [];
  const total = data?.total ?? 0;
  const hasFilters = Object.keys(filters).length > 0;

  function filterLabel(key: string, value: string): string {
    if (key === "account_id") {
      const a = accounts.find((a) => String(a.id) === value);
      return a ? a.name : `Account #${value}`;
    }
    if (key === "status") return value;
    if (key === "date_from") return `From ${new Date(value).toLocaleDateString()}`;
    if (key === "date_to") return `To ${new Date(value).toLocaleDateString()}`;
    return `${key}: ${value}`;
  }

  return (
    <Layout>
      <div className="flex items-center justify-between mb-3">
        <h1 className="text-xl font-bold">Transactions</h1>
        <div className="flex gap-2">
          <SnapReceiptButton label="" variant="outline" />
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
              className="inline-flex items-center gap-1 rounded-full bg-sky-50 border border-sky-200 px-2.5 py-0.5 text-xs text-sky-700"
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
            className="text-xs text-gray-500 hover:text-gray-700 px-1"
          >
            Clear all
          </button>
        </div>
      )}

      {/* Transfer detection result */}
      {detectResult && (
        <div className="rounded-lg border border-sky-200 bg-sky-50 p-2.5 mb-3 flex items-center justify-between">
          <p className="text-sm text-sky-800">
            {detectResult.new_pairs > 0
              ? `Found ${detectResult.new_pairs} new transfer pair${detectResult.new_pairs !== 1 ? "s" : ""} (${detectResult.total_pairs} total).`
              : `No new transfers found (${detectResult.total_pairs} existing).`}
          </p>
          <button onClick={() => setDetectResult(null)} className="text-sky-500 hover:text-sky-700">
            <X className="h-4 w-4" />
          </button>
        </div>
      )}

      {isLoading ? (
        <p className="text-gray-500 text-sm">Loading…</p>
      ) : items.length === 0 ? (
        <p className="text-gray-500 text-sm">
          No transactions{hasFilters ? " match your filters" : " yet"}.
        </p>
      ) : (
        <>
          <div className="text-xs text-gray-500 mb-2">
            {total.toLocaleString()} transactions
          </div>

          {/* Table */}
          <div className="overflow-x-auto rounded-lg border border-gray-200">
            <table className="w-full text-sm">
              <thead>
                <tr className="bg-gray-50 border-b border-gray-200">
                  <SortHeader field="posted_at" label="Date" current={sortBy} dir={sortDir} onSort={toggleSort} />
                  <th className="px-3 py-2 text-left font-medium text-gray-600 text-xs">Description</th>
                  <th className="px-3 py-2 text-left font-medium text-gray-600 text-xs">Account</th>
                  <th className="px-3 py-2 text-left font-medium text-gray-600 text-xs">Category</th>
                  <SortHeader field="amount_cents" label="Amount" current={sortBy} dir={sortDir} onSort={toggleSort} className="text-right" />
                  <SortHeader field="status" label="Status" current={sortBy} dir={sortDir} onSort={toggleSort} />
                  <th className="px-2 py-2 w-8" />
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {items.map((t) => (
                  <tr
                    key={t.id}
                    onClick={() => setSelectedId(t.id)}
                    className="hover:bg-gray-50 cursor-pointer"
                  >
                    <td className="px-3 py-2 text-xs text-gray-600 whitespace-nowrap">
                      {new Date(t.posted_at).toLocaleDateString()}
                    </td>
                    <td className="px-3 py-2 max-w-[200px]">
                      <div className="truncate font-medium text-gray-900">
                        {t.merchant_name || t.description || "—"}
                      </div>
                      {t.merchant_name && t.description && t.merchant_name !== t.description && (
                        <div className="truncate text-xs text-gray-400">{t.description}</div>
                      )}
                    </td>
                    <td className="px-3 py-2 text-xs text-gray-600 whitespace-nowrap">
                      {t.account_name ?? "—"}
                    </td>
                    <td className="px-3 py-2 text-xs text-gray-600 whitespace-nowrap">
                      {t.category_name ?? "—"}
                    </td>
                    <td className="px-3 py-2 text-right font-semibold tabular-nums whitespace-nowrap">
                      {formatCents(t.amount_cents)}
                    </td>
                    <td className="px-3 py-2">
                      <div className="flex items-center gap-1">
                        <span
                          className={cn(
                            "inline-block rounded px-1.5 py-0.5 text-[10px] font-medium",
                            t.status === "split"
                              ? "bg-green-100 text-green-700"
                              : t.status === "final"
                                ? "bg-sky-100 text-sky-700"
                                : "bg-gray-100 text-gray-600"
                          )}
                        >
                          {t.status}
                        </span>
                        {t.transfer_pair_id && (
                          <span
                            className="inline-block rounded px-1.5 py-0.5 text-[10px] font-medium bg-violet-100 text-violet-700"
                            title={`Transfer pair #${t.transfer_pair_id}`}
                          >
                            xfer
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
              <span className="text-xs text-gray-500">
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
          <div>
            <Label>From</Label>
            <input
              type="date"
              value={dateFrom}
              onChange={(e) => setDateFrom(e.target.value)}
              className="flex h-10 w-full rounded-md border border-gray-300 bg-white px-3 py-2 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-500"
            />
          </div>
          <div>
            <Label>To</Label>
            <input
              type="date"
              value={dateTo}
              onChange={(e) => setDateTo(e.target.value)}
              className="flex h-10 w-full rounded-md border border-gray-300 bg-white px-3 py-2 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-500"
            />
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
          <div>
            <Label>Status</Label>
            <Select
              value={filterStatus}
              onChange={(e) => setFilterStatus(e.target.value)}
            >
              <option value="">All</option>
              <option value="pending">Pending</option>
              <option value="split">Split</option>
              <option value="final">Final</option>
            </Select>
          </div>
          <div className="flex justify-end gap-2 pt-2">
            <Button
              variant="outline"
              onClick={() => {
                clearFilters();
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
            <div className="rounded-lg border border-gray-200 p-2 bg-gray-50">
              <p className="text-xs text-gray-500 mb-1">Attached receipt</p>
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
              className="flex h-10 w-full rounded-md border border-gray-300 bg-white px-3 py-2 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-500"
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

function SortHeader({
  field,
  label,
  current,
  dir,
  onSort,
  className,
}: {
  field: SortField;
  label: string;
  current: SortField;
  dir: SortDir;
  onSort: (f: SortField) => void;
  className?: string;
}) {
  const active = current === field;
  return (
    <th
      className={cn(
        "px-3 py-2 font-medium text-xs cursor-pointer select-none hover:text-gray-900 whitespace-nowrap",
        active ? "text-gray-900" : "text-gray-600",
        className,
      )}
      onClick={() => onSort(field)}
    >
      <span className="inline-flex items-center gap-1">
        {label}
        {active ? (
          dir === "asc" ? <ArrowUp className="h-3 w-3" /> : <ArrowDown className="h-3 w-3" />
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
}: {
  txnId: number;
  onBack: () => void;
}) {
  const { data: txn, isLoading } = useTransaction(txnId);
  const replaceMut = useReplaceLineItems();

  const [splits, setSplits] = useState<LineItemInput[] | null>(null);
  const [dirty, setDirty] = useState(false);

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
    setDirty(false);
    setSplits(null);
  }

  const prefilled =
    txn &&
    txn.line_items.length === 1 &&
    txn.line_items[0].category_name === "Uncategorized" &&
    txn.merchant_id;

  if (isLoading || !txn) {
    return (
      <Layout>
        <button onClick={onBack} className="flex items-center text-sm text-sky-600 mb-4">
          <ChevronLeft className="h-4 w-4" />
          Back
        </button>
        <p className="text-gray-500 text-sm">Loading…</p>
      </Layout>
    );
  }

  const allocated = currentSplits.reduce((s, i) => s + i.amount_cents, 0);
  const balanced = allocated === txn.amount_cents;
  const validCategories = currentSplits.every((s) => s.category_id > 0);

  return (
    <Layout>
      <button
        onClick={onBack}
        className="flex items-center text-sm text-sky-600 mb-4"
      >
        <ChevronLeft className="h-4 w-4" />
        Back
      </button>

      <div className="bg-white rounded-lg border border-gray-200 p-4 mb-4">
        <div className="flex justify-between items-start">
          <div>
            <h2 className="font-semibold">
              {txn.merchant_name || txn.description || "Transaction"}
            </h2>
            <p className="text-xs text-gray-500">
              {new Date(txn.posted_at).toLocaleDateString()}
            </p>
          </div>
          <span className="text-lg font-bold">
            {formatCents(txn.amount_cents)}
          </span>
        </div>
        {txn.description && txn.merchant_name && (
          <p className="text-sm text-gray-600 mt-1">{txn.description}</p>
        )}
        {txn.receipt_id && (
          <img
            src={receiptImageUrl(txn.receipt_id)}
            alt="Receipt"
            className="mt-3 max-h-40 mx-auto rounded border border-gray-200"
          />
        )}
      </div>

      <h3 className="text-sm font-semibold mb-2">Line Items</h3>

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

      {dirty && (
        <div className="mt-4">
          <Button
            onClick={handleSave}
            disabled={!balanced || !validCategories || replaceMut.isPending}
            className="w-full"
          >
            {replaceMut.isPending ? "Saving…" : "Save Splits"}
          </Button>
        </div>
      )}
    </Layout>
  );
}
