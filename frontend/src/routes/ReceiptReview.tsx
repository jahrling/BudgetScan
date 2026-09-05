import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import {
  Check,
  ChevronDown,
  ChevronUp,
  Edit3,
  Loader2,
  Trash2,
  Plus,
} from "lucide-react";
import { Layout } from "../components/Layout";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { Label } from "../components/ui/label";
import { Select } from "../components/ui/select";
import { CategoryPicker } from "../components/CategoryPicker";
import { MoneyInput, formatCents } from "../components/MoneyInput";
import {
  receiptImageUrl,
  useOcrPreview,
  useReviewToTransaction,
} from "../hooks/useReceipts";
import { useAccounts } from "../hooks/useAccounts";
import type { ReviewLineItem } from "../types/models";

interface EditableItem extends ReviewLineItem {
  original_amount_cents: number;
  original_description: string | null;
  original_category_id: number;
}

export default function ReceiptReview() {
  const { id } = useParams<{ id: string }>();
  const receiptId = id ? Number(id) : null;
  const navigate = useNavigate();
  const { data: preview, isLoading, isError } = useOcrPreview(receiptId);
  const { data: accounts = [] } = useAccounts();
  const submit = useReviewToTransaction();

  const [merchantName, setMerchantName] = useState("");
  const [postedAt, setPostedAt] = useState("");
  const [accountId, setAccountId] = useState<number | null>(null);
  const [items, setItems] = useState<EditableItem[]>([]);
  const [imageExpanded, setImageExpanded] = useState(false);
  const [initialized, setInitialized] = useState(false);

  useEffect(() => {
    if (accountId === null && accounts.length === 1) {
      setAccountId(accounts[0].id);
    }
  }, [accounts, accountId]);

  useEffect(() => {
    if (!preview || initialized) return;
    setMerchantName(preview.merchant || "");
    setPostedAt(preview.date || new Date().toISOString().slice(0, 10));
    setItems(
      preview.items.map((it) => ({
        description: it.description,
        quantity: it.quantity,
        unit_price_cents: it.unit_price_cents,
        amount_cents: it.amount_cents,
        category_id: it.suggested_category_id,
        user_modified: false,
        original_amount_cents: it.amount_cents,
        original_description: it.description,
        original_category_id: it.suggested_category_id,
      })),
    );
    setInitialized(true);
  }, [preview, initialized]);

  if (!receiptId) {
    return (
      <Layout>
        <p className="text-red-600">Bad URL.</p>
      </Layout>
    );
  }

  if (isLoading || !preview) {
    return (
      <Layout>
        <div className="text-center py-12">
          <Loader2 className="h-6 w-6 mx-auto animate-spin text-gray-400" />
          <p className="text-sm text-gray-500 mt-2">Loading OCR results…</p>
        </div>
      </Layout>
    );
  }

  if (isError) {
    return (
      <Layout>
        <p className="text-red-600">Could not load OCR preview.</p>
        <Button
          variant="outline"
          className="mt-4"
          onClick={() => navigate(-1)}
        >
          Go back
        </Button>
      </Layout>
    );
  }

  const totalCents = preview.total_cents;
  const itemsSum = items.reduce((s, i) => s + i.amount_cents, 0);
  const drift = totalCents - itemsSum;

  function updateItem(idx: number, patch: Partial<EditableItem>) {
    setItems((prev) =>
      prev.map((item, i) => {
        if (i !== idx) return item;
        const next = { ...item, ...patch };
        const changed =
          next.amount_cents !== item.original_amount_cents ||
          next.description !== item.original_description ||
          next.category_id !== item.original_category_id;
        return { ...next, user_modified: changed };
      }),
    );
  }

  function removeItem(idx: number) {
    setItems((prev) => prev.filter((_, i) => i !== idx));
  }

  function addItem() {
    const remaining = Math.max(drift, 0);
    setItems((prev) => [
      ...prev,
      {
        description: "",
        quantity: null,
        unit_price_cents: null,
        amount_cents: remaining,
        category_id: 0,
        user_modified: true,
        original_amount_cents: 0,
        original_description: null,
        original_category_id: 0,
      },
    ]);
  }

  function handleSubmit() {
    if (!accountId) return;
    submit.mutate(
      {
        receiptId: receiptId!,
        account_id: accountId,
        merchant_name: merchantName || null,
        merchant_id: null,
        posted_at: new Date(postedAt + "T00:00:00Z").toISOString(),
        total_cents: totalCents,
        items: items.map((it) => ({
          description: it.description,
          quantity: it.quantity,
          unit_price_cents: it.unit_price_cents,
          amount_cents: it.amount_cents,
          category_id: it.category_id,
          user_modified: it.user_modified,
        })),
      },
      {
        onSuccess: (txn) => {
          navigate(`/transactions?open=${txn.id}`, { replace: true });
        },
      },
    );
  }

  return (
    <Layout>
      <div className="space-y-4 pb-4">
        <h1 className="text-lg font-semibold text-gray-900 dark:text-gray-100">Review receipt</h1>

        {/* Receipt image */}
        <div>
          <button
            type="button"
            onClick={() => setImageExpanded(!imageExpanded)}
            className="w-full flex items-center justify-between text-sm text-gray-500 mb-1"
          >
            <span>Receipt image</span>
            {imageExpanded ? (
              <ChevronUp className="h-4 w-4" />
            ) : (
              <ChevronDown className="h-4 w-4" />
            )}
          </button>
          <img
            src={receiptImageUrl(receiptId)}
            alt="Receipt"
            className={`rounded-lg border border-gray-200 dark:border-gray-700 mx-auto transition-all ${
              imageExpanded ? "max-h-[80vh]" : "max-h-32"
            }`}
          />
        </div>

        {/* Merchant & date */}
        <div className="rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 p-3 space-y-3">
          <div>
            <Label className="text-xs text-gray-500">Merchant</Label>
            <Input
              value={merchantName}
              onChange={(e) => setMerchantName(e.target.value)}
              placeholder="Merchant name"
              className="h-9 text-sm"
            />
          </div>
          <div className="flex gap-3">
            <div className="flex-1">
              <Label className="text-xs text-gray-500">Date</Label>
              <Input
                type="date"
                value={postedAt}
                onChange={(e) => setPostedAt(e.target.value)}
                className="h-9 text-sm"
              />
            </div>
            <div className="flex-1">
              <Label className="text-xs text-gray-500">Total</Label>
              <div className="h-9 flex items-center text-sm font-semibold text-gray-900 dark:text-gray-100 px-3 border border-gray-200 dark:border-gray-700 rounded-md bg-gray-50 dark:bg-gray-700">
                {formatCents(totalCents)}
              </div>
            </div>
          </div>
          {preview.tax_cents != null && preview.tax_cents > 0 && (
            <div className="text-xs text-gray-500">
              Tax: {formatCents(preview.tax_cents)}
              {preview.subtotal_cents != null &&
                ` · Subtotal: ${formatCents(preview.subtotal_cents)}`}
            </div>
          )}
        </div>

        {/* Account */}
        {accounts.length > 1 && (
          <div className="rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 p-3">
            <Label className="text-xs text-gray-500 dark:text-gray-400">Account</Label>
            <Select
              value={accountId ?? ""}
              onChange={(e) =>
                setAccountId(e.target.value ? Number(e.target.value) : null)
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
          </div>
        )}

        {/* Line items */}
        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <h2 className="text-sm font-semibold text-gray-700 dark:text-gray-300">
              Items ({items.length})
            </h2>
            <span
              className={`text-xs font-medium px-2 py-0.5 rounded-full ${
                drift === 0
                  ? "bg-green-100 dark:bg-green-900/40 text-green-700 dark:text-green-300"
                  : Math.abs(drift) <= 100
                    ? "bg-amber-100 dark:bg-amber-900/40 text-amber-700 dark:text-amber-300"
                    : "bg-red-100 dark:bg-red-900/40 text-red-700 dark:text-red-300"
              }`}
            >
              {drift === 0
                ? "Balanced"
                : drift > 0
                  ? `${formatCents(drift)} unallocated`
                  : `${formatCents(Math.abs(drift))} over`}
            </span>
          </div>

          {items.map((item, idx) => (
            <div
              key={idx}
              className={`rounded-lg border bg-white dark:bg-gray-800 p-3 space-y-2 ${
                item.user_modified
                  ? "border-sky-300 dark:border-sky-700 ring-1 ring-sky-100 dark:ring-sky-900"
                  : "border-gray-200 dark:border-gray-700"
              }`}
            >
              <div className="flex items-start gap-2">
                <div className="flex-1 min-w-0 space-y-2">
                  <Input
                    value={item.description ?? ""}
                    onChange={(e) =>
                      updateItem(idx, {
                        description: e.target.value || null,
                      })
                    }
                    placeholder="Item description"
                    className="h-8 text-sm"
                  />
                  <div className="flex gap-2">
                    <div className="flex-1">
                      <CategoryPicker
                        value={item.category_id || null}
                        onValueChange={(id) =>
                          updateItem(idx, { category_id: id ?? 0 })
                        }
                        className="h-8 text-xs"
                      />
                    </div>
                    <div className="w-24 shrink-0">
                      <MoneyInput
                        valueCents={item.amount_cents}
                        onValueChange={(cents) =>
                          updateItem(idx, { amount_cents: cents })
                        }
                        className="h-8 text-sm"
                      />
                    </div>
                  </div>
                  {item.quantity != null && (
                    <p className="text-xs text-gray-400">
                      {item.quantity} ×{" "}
                      {item.unit_price_cents != null
                        ? formatCents(item.unit_price_cents)
                        : "?"}
                    </p>
                  )}
                </div>
                <button
                  type="button"
                  onClick={() => removeItem(idx)}
                  className="shrink-0 p-1 text-gray-400 hover:text-red-500"
                >
                  <Trash2 className="h-4 w-4" />
                </button>
              </div>
              {item.user_modified && (
                <div className="flex items-center gap-1 text-xs text-sky-600">
                  <Edit3 className="h-3 w-3" />
                  <span>Modified</span>
                </div>
              )}
            </div>
          ))}

          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={addItem}
            className="w-full"
          >
            <Plus className="h-3.5 w-3.5 mr-1" />
            Add item
          </Button>
        </div>

        {/* Drift / tax rounding note */}
        {drift !== 0 && (
          <div className="text-xs text-gray-500 dark:text-gray-400 bg-gray-50 dark:bg-gray-800 rounded-lg p-2">
            {Math.abs(drift) <= 100
              ? `A "${drift > 0 ? "Tax / rounding" : "Adjustment"}" line of ${formatCents(Math.abs(drift))} will be added automatically.`
              : `Items are ${formatCents(Math.abs(drift))} ${drift > 0 ? "under" : "over"} the total. Adjust items or a balancer line will be created.`}
          </div>
        )}

        {/* Submit */}
        <Button
          className="w-full"
          disabled={!accountId || items.length === 0 || submit.isPending}
          onClick={handleSubmit}
        >
          {submit.isPending ? (
            <>
              <Loader2 className="h-4 w-4 mr-2 animate-spin" />
              Saving…
            </>
          ) : (
            <>
              <Check className="h-4 w-4 mr-2" />
              Save transaction
            </>
          )}
        </Button>

        {submit.isError && (
          <p className="text-sm text-red-600 text-center">
            {(submit.error as Error).message}
          </p>
        )}
      </div>
    </Layout>
  );
}
