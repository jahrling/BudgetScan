import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { AlertTriangle, Loader2 } from "lucide-react";
import { Layout } from "../components/Layout";
import { Button } from "../components/ui/button";
import { Label } from "../components/ui/label";
import { Select } from "../components/ui/select";
import {
  receiptImageUrl,
  useReceipt,
  useReceiptToTransaction,
  useReprocessReceipt,
} from "../hooks/useReceipts";
import { useAccounts } from "../hooks/useAccounts";

const POLL_TIMEOUT_MS = 60_000;

export default function ReceiptProcessing() {
  const { id } = useParams<{ id: string }>();
  const receiptId = id ? Number(id) : null;
  const navigate = useNavigate();
  const { data: receipt, refetch } = useReceipt(receiptId);
  const { data: accounts = [] } = useAccounts();
  const toTxn = useReceiptToTransaction();
  const reprocess = useReprocessReceipt();

  const startedAt = useRef<number>(Date.now());
  const [timedOut, setTimedOut] = useState(false);
  const [accountId, setAccountId] = useState<number | null>(null);
  const [autoBlocked, setAutoBlocked] = useState(false);

  // Pre-select the account if there's exactly one.
  useEffect(() => {
    if (accountId === null && accounts.length === 1) {
      setAccountId(accounts[0].id);
    }
  }, [accounts, accountId]);

  // 60-second timeout — flips to a manual retry/cancel UI.
  useEffect(() => {
    if (!receipt || receipt.ocr_status !== "pending") return;
    const t = window.setTimeout(() => {
      if (receipt.ocr_status === "pending") setTimedOut(true);
    }, POLL_TIMEOUT_MS - (Date.now() - startedAt.current));
    return () => window.clearTimeout(t);
  }, [receipt]);

  // Once OCR is done, auto-materialize a transaction and route to its detail.
  useEffect(() => {
    if (!receipt || !receiptId) return;
    if (receipt.ocr_status !== "done") return;
    if (autoBlocked) return;
    if (!accountId) {
      setAutoBlocked(true);
      return;
    }
    if (toTxn.isPending || toTxn.isSuccess) return;

    toTxn
      .mutateAsync({ receiptId, account_id: accountId })
      .then((txn) => {
        navigate(`/transactions?open=${txn.id}`, { replace: true });
      })
      .catch(() => {
        /* error shown below */
      });
  }, [receipt, receiptId, accountId, autoBlocked, toTxn, navigate]);

  const elapsedSec = useMemo(
    () => Math.floor((Date.now() - startedAt.current) / 1000),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [receipt?.updated_at]
  );

  if (!receiptId) {
    return (
      <Layout>
        <p className="text-red-600">Bad URL.</p>
      </Layout>
    );
  }

  if (!receipt) {
    return (
      <Layout>
        <div className="text-center py-12">
          <Loader2 className="h-6 w-6 mx-auto animate-spin text-gray-400" />
        </div>
      </Layout>
    );
  }

  if (receipt.ocr_status === "failed") {
    return (
      <Layout>
        <div className="space-y-4">
          <div className="flex items-start gap-2 rounded-lg border border-red-200 bg-red-50 p-3">
            <AlertTriangle className="h-5 w-5 text-red-500 shrink-0 mt-0.5" />
            <div className="text-sm">
              <p className="font-semibold text-red-700">Could not read receipt</p>
              <p className="text-red-700">{receipt.ocr_error || "Unknown error"}</p>
            </div>
          </div>

          <img
            src={receiptImageUrl(receipt.id)}
            alt="Receipt"
            className="rounded-lg border border-gray-200 max-h-64 mx-auto"
          />

          <div className="flex gap-2">
            <Button
              variant="outline"
              className="flex-1"
              onClick={() => reprocess.mutate(receipt.id, { onSuccess: () => refetch() })}
              disabled={reprocess.isPending}
            >
              Try again
            </Button>
            <Button
              className="flex-1"
              onClick={() =>
                navigate(`/transactions?manual=${receipt.id}`, { replace: true })
              }
            >
              Enter manually
            </Button>
          </div>
        </div>
      </Layout>
    );
  }

  if (receipt.ocr_status === "done" && autoBlocked) {
    // OCR done but we don't know which account to attach to.
    return (
      <Layout>
        <h1 className="text-lg font-semibold mb-3">Pick account</h1>
        <img
          src={receiptImageUrl(receipt.id)}
          alt="Receipt"
          className="rounded-lg border border-gray-200 max-h-48 mx-auto mb-4"
        />
        <Label>Account</Label>
        <Select
          value={accountId ?? ""}
          onChange={(e) => setAccountId(e.target.value ? Number(e.target.value) : null)}
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
        <Button
          className="w-full mt-4"
          disabled={!accountId || toTxn.isPending}
          onClick={() => setAutoBlocked(false)}
        >
          {toTxn.isPending ? "Creating…" : "Continue"}
        </Button>
      </Layout>
    );
  }

  // Pending — show image thumbnail + spinner, plus timeout escape hatch.
  return (
    <Layout>
      <div className="text-center">
        <img
          src={receiptImageUrl(receipt.id)}
          alt="Receipt"
          className="rounded-lg border border-gray-200 max-h-72 mx-auto mb-4"
        />
        <div className="flex items-center justify-center gap-2 text-gray-600">
          <Loader2 className="h-5 w-5 animate-spin" />
          <span className="text-sm">
            {toTxn.isPending ? "Building transaction…" : "Reading receipt…"}
          </span>
        </div>
        <p className="text-xs text-gray-400 mt-1">{elapsedSec}s elapsed</p>

        {timedOut && (
          <div className="mt-6 space-y-2">
            <p className="text-sm text-amber-600">
              Still working? OCR usually takes 5–15s. The model may be loading or the
              server might be slow.
            </p>
            <div className="flex gap-2">
              <Button
                variant="outline"
                className="flex-1"
                onClick={() => {
                  setTimedOut(false);
                  startedAt.current = Date.now();
                  refetch();
                }}
              >
                Keep waiting
              </Button>
              <Button
                className="flex-1"
                onClick={() =>
                  navigate(`/transactions?manual=${receipt.id}`, { replace: true })
                }
              >
                Enter manually
              </Button>
            </div>
          </div>
        )}

        {toTxn.isError && (
          <p className="mt-3 text-sm text-red-600">
            Couldn't create transaction: {(toTxn.error as Error).message}
          </p>
        )}
      </div>
    </Layout>
  );
}
