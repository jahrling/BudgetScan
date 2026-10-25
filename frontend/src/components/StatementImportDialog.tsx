import { useEffect, useRef, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, ArrowUpDown, CheckCircle2, Upload } from "lucide-react";
import { Dialog, DialogTitle } from "./ui/dialog";
import { Button } from "./ui/button";
import { Label } from "./ui/label";
import { Select } from "./ui/select";
import { apiFetch } from "../lib/api";
import { formatCents } from "./MoneyInput";
import { useAccounts } from "../hooks/useAccounts";
import {
  CandidateReview,
  defaultActionFor,
  type ParseResult,
  type RowAction,
} from "./ImportCandidateReview";

interface StatementParseResult extends ParseResult {
  format: "csv" | "ofx" | "pdf";
  inverted: boolean | null;
  columns: Record<string, string>;
}

interface Reconciliation {
  previous_balance_cents: number | null;
  new_balance_cents: number | null;
  charges_cents: number;
  credits_cents: number;
  difference_cents: number | null;
}

interface PdfJob {
  job_id: string;
  status: "running" | "done" | "failed";
  pages_done: number;
  pages_total: number;
  error: string | null;
  result: StatementParseResult | null;
  reconciliation: Reconciliation | null;
}

const PDF_POLL_MS = 1500;

function isPdf(file: File): boolean {
  return file.type === "application/pdf" || file.name.toLowerCase().endsWith(".pdf");
}

async function errorDetail(res: Response): Promise<string> {
  const detail = await res.json().then((b) => b.detail).catch(() => null);
  return typeof detail === "string" ? detail : `HTTP ${res.status}`;
}

interface ConfirmResult {
  created_ids: number[];
  merged_ids: number[];
  overwritten_ids: number[];
  skipped: number;
  errors: string[];
}

const LAST_ACCOUNT_KEY = "statementImport.accountId";

function readLastAccount(): number | null {
  try {
    const v = localStorage.getItem(LAST_ACCOUNT_KEY);
    return v ? Number(v) : null;
  } catch {
    return null;
  }
}

function writeLastAccount(id: number) {
  try {
    localStorage.setItem(LAST_ACCOUNT_KEY, String(id));
  } catch {
    // storage unavailable — just don't remember
  }
}

/**
 * Upload a credit card / bank statement (CSV or QFX/OFX) into one account,
 * review duplicates, then apply via the shared /api/import/confirm flow.
 */
export function StatementImportDialog({
  open,
  onClose,
  onImported,
}: {
  open: boolean;
  onClose: () => void;
  /** Called after a successful apply with the account and earliest date imported. */
  onImported?: (accountId: number, earliest: string) => void;
}) {
  const qc = useQueryClient();
  const { data: accounts = [] } = useAccounts();
  const [pickedAccountId, setPickedAccountId] = useState<number | null>(readLastAccount);
  const [file, setFile] = useState<File | null>(null);
  const [parsed, setParsed] = useState<StatementParseResult | null>(null);
  const [actions, setActions] = useState<RowAction[]>([]);
  const [createMissing, setCreateMissing] = useState(false);
  const [confirmResult, setConfirmResult] = useState<ConfirmResult | null>(null);
  const [dragging, setDragging] = useState(false);
  const [pdfProgress, setPdfProgress] = useState<{ done: number; total: number } | null>(null);
  const [reconciliation, setReconciliation] = useState<Reconciliation | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  // Bumped on close/reset so an in-flight PDF poll loop knows to stop.
  const pollGeneration = useRef(0);
  useEffect(() => () => { pollGeneration.current++; }, []);

  // Credit cards first — that's what this is mostly for.
  const sortedAccounts = [...accounts].sort(
    (a, b) => Number(b.type === "credit") - Number(a.type === "credit") || a.name.localeCompare(b.name),
  );
  const accountId =
    pickedAccountId !== null && accounts.some((a) => a.id === pickedAccountId)
      ? pickedAccountId
      : sortedAccounts[0]?.id ?? null;

  const uploadMut = useMutation({
    mutationFn: async ({ file, invert }: { file: File; invert?: boolean }) => {
      if (accountId === null) throw new Error("Pick an account first");
      const form = new FormData();
      form.append("file", file);
      form.append("account_id", String(accountId));
      if (!isPdf(file)) {
        if (invert !== undefined) form.append("invert", String(invert));
        const res = await fetch("/api/import/statement", {
          method: "POST",
          credentials: "include",
          body: form,
        });
        if (!res.ok) throw new Error(await errorDetail(res));
        return { result: (await res.json()) as StatementParseResult, reconciliation: null };
      }

      // PDFs are read by the local LLM in a background job; poll until done.
      const generation = ++pollGeneration.current;
      const res = await fetch("/api/import/statement-pdf", {
        method: "POST",
        credentials: "include",
        body: form,
      });
      // Closed or reset while awaiting? Don't show a review for the old file.
      const checkCancelled = () => {
        if (generation !== pollGeneration.current) throw new Error("Cancelled");
      };
      if (!res.ok) throw new Error(await errorDetail(res));
      let job = (await res.json()) as PdfJob;
      checkCancelled();
      while (job.status === "running") {
        setPdfProgress({ done: job.pages_done, total: job.pages_total });
        await new Promise((r) => setTimeout(r, PDF_POLL_MS));
        checkCancelled();
        job = await apiFetch<PdfJob>(`/api/import/statement-pdf/${job.job_id}`);
        checkCancelled();
      }
      setPdfProgress(null);
      if (job.status === "failed" || !job.result) {
        throw new Error(job.error ?? "Couldn't read the statement");
      }
      return { result: job.result, reconciliation: job.reconciliation };
    },
    onError: () => setPdfProgress(null),
    onSuccess: ({ result: data, reconciliation }) => {
      setReconciliation(reconciliation);
      setParsed(data);
      setActions(data.candidates.map(defaultActionFor));
      setConfirmResult(null);
    },
  });

  const confirmMut = useMutation({
    mutationFn: async () => {
      if (!parsed) throw new Error("no parsed data");
      return apiFetch<ConfirmResult>("/api/import/confirm", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          candidates: parsed.candidates.map(
            ({ match_description, match_amount_cents, match_posted_at, match_category_path, ...c }) => c,
          ),
          actions: actions.map((a, i) => ({ candidate_index: i, action: a })),
          create_missing_categories: createMissing,
        }),
      });
    },
    onSuccess: (data) => {
      setConfirmResult(data);
      if (data.errors.length === 0) {
        qc.invalidateQueries({ queryKey: ["transactions"] });
        qc.invalidateQueries({ queryKey: ["budgets"] });
        if (accountId !== null && parsed && parsed.candidates.length > 0) {
          const earliest = parsed.candidates.reduce(
            (min, c) => (c.posted_at < min ? c.posted_at : min),
            parsed.candidates[0].posted_at,
          );
          onImported?.(accountId, earliest);
        }
      }
    },
  });

  function handleFile(f: File) {
    if (accountId !== null) writeLastAccount(accountId);
    setFile(f);
    uploadMut.mutate({ file: f });
  }

  function reset() {
    pollGeneration.current++;
    setPdfProgress(null);
    setReconciliation(null);
    setFile(null);
    setParsed(null);
    setActions([]);
    setConfirmResult(null);
    uploadMut.reset();
    confirmMut.reset();
  }

  function close() {
    reset();
    onClose();
  }

  const done = confirmResult !== null && confirmResult.errors.length === 0;

  return (
    <Dialog open={open} onClose={close} className="max-w-2xl">
      <DialogTitle>Import statement</DialogTitle>

      {!parsed ? (
        <div className="space-y-4">
          <p className="text-sm text-gray-600 dark:text-gray-400">
            On your card issuer's website, download your activity as <strong>CSV</strong> or{" "}
            <strong>QFX / OFX</strong> (sometimes labelled "Quicken" or "Money"), or upload the monthly{" "}
            <strong>PDF statement</strong>. PDFs are read by your local AI model and take a minute or two.
          </p>

          <div>
            <Label htmlFor="statement-account" className="text-xs">Account</Label>
            <Select
              id="statement-account"
              value={accountId ?? ""}
              onChange={(e) => setPickedAccountId(Number(e.target.value))}
              disabled={uploadMut.isPending}
            >
              {sortedAccounts.map((a) => (
                <option key={a.id} value={a.id}>
                  {a.name}
                </option>
              ))}
            </Select>
          </div>

          <div
            onClick={() => accountId !== null && fileInputRef.current?.click()}
            onDrop={(e) => {
              e.preventDefault();
              e.stopPropagation();
              setDragging(false);
              const f = e.dataTransfer.files[0];
              if (f && accountId !== null) handleFile(f);
            }}
            onDragOver={(e) => {
              e.preventDefault();
              e.stopPropagation();
              setDragging(true);
            }}
            onDragLeave={(e) => {
              if (e.currentTarget.contains(e.relatedTarget as Node)) return;
              setDragging(false);
            }}
            className={`flex flex-col items-center justify-center rounded-lg border-2 border-dashed p-6 text-center cursor-pointer transition-colors ${
              dragging
                ? "border-sky-400 bg-sky-50 dark:bg-sky-900/30"
                : "border-gray-300 dark:border-gray-600 hover:border-sky-400"
            }`}
          >
            <input
              ref={fileInputRef}
              type="file"
              accept=".csv,.qfx,.ofx,.pdf,text/csv,application/pdf"
              onChange={(e) => {
                const f = e.target.files?.[0];
                if (f) handleFile(f);
                e.target.value = "";
              }}
              className="hidden"
              disabled={uploadMut.isPending}
            />
            {uploadMut.isPending ? (
              <>
                <span className="inline-block h-3 w-3 rounded-sm bg-sky-500 mb-3 animate-pulse" />
                <p className="text-sm text-gray-500">
                  {pdfProgress
                    ? pdfProgress.total > 0
                      ? `Reading page ${Math.min(pdfProgress.done + 1, pdfProgress.total)} of ${pdfProgress.total} with local AI…`
                      : "Reading statement with local AI…"
                    : `Parsing ${file?.name}…`}
                </p>
              </>
            ) : (
              <>
                <Upload className={`h-8 w-8 mb-2 ${dragging ? "text-sky-400" : "text-gray-400"}`} />
                <p className="text-sm font-medium text-gray-900 dark:text-gray-100">
                  {dragging ? "Drop file here" : "Drag & drop a PDF, CSV, or QFX file"}
                </p>
                <p className="mt-1 text-xs text-gray-500">or click to browse</p>
              </>
            )}
          </div>

          {accounts.length === 0 && (
            <p className="text-sm text-amber-700 dark:text-amber-400">
              Create the account first under Sync → Accounts.
            </p>
          )}

          {uploadMut.isError && (
            <p className="text-sm text-red-600 dark:text-red-400">
              {uploadMut.error instanceof Error ? uploadMut.error.message : String(uploadMut.error)}
            </p>
          )}
        </div>
      ) : (
        <>
          <div className="flex flex-wrap items-center justify-between gap-2 rounded-md bg-gray-50 dark:bg-gray-900/40 border border-gray-200 dark:border-gray-700 px-3 py-2 text-xs text-gray-600 dark:text-gray-400">
            <span className="min-w-0 truncate">
              {file?.name} · {{ ofx: "QFX/OFX", csv: "CSV", pdf: "PDF (AI-read)" }[parsed.format]} →{" "}
              <span className="font-medium text-gray-800 dark:text-gray-200">
                {accounts.find((a) => a.id === accountId)?.name}
              </span>
            </span>
            <div className="flex gap-2">
              {parsed.inverted !== null && !done && file && (
                <Button
                  variant="outline"
                  size="sm"
                  title="Charges should be negative. Flip if this statement's signs came out backwards."
                  disabled={uploadMut.isPending}
                  onClick={() => uploadMut.mutate({ file, invert: !parsed.inverted })}
                >
                  <ArrowUpDown className="h-3.5 w-3.5 mr-1" />
                  Flip signs
                </Button>
              )}
              {!done && (
                <Button variant="outline" size="sm" onClick={reset}>
                  Different file
                </Button>
              )}
            </div>
          </div>
          {parsed.inverted !== null && (
            <p className="mt-2 text-xs text-gray-500">
              Charges should show as negative amounts. If they don't, use Flip signs.
            </p>
          )}

          {parsed.format === "pdf" && <ReconciliationBanner rec={reconciliation} />}

          <CandidateReview
            parsed={parsed}
            setParsed={(p) => setParsed({ ...parsed, ...p })}
            actions={actions}
            setActions={setActions}
            createMissing={createMissing}
            setCreateMissing={setCreateMissing}
            confirmMut={confirmMut}
            confirmResult={confirmResult}
            accounts={accounts}
            inDialog
          />

          {done && (
            <div className="mt-3 flex justify-end">
              <Button onClick={close}>Done</Button>
            </div>
          )}
        </>
      )}
    </Dialog>
  );
}

/**
 * The AI can drop or misread a row; the statement's own balances catch that.
 * previous + charges − credits should equal the new balance.
 */
function ReconciliationBanner({ rec }: { rec: Reconciliation | null }) {
  if (!rec || rec.difference_cents === null) {
    return (
      <div className="mt-3 flex gap-2 rounded-lg border border-amber-300 dark:border-amber-800 bg-amber-50 dark:bg-amber-900/30 p-3 text-sm text-amber-800 dark:text-amber-300">
        <AlertTriangle className="h-4 w-4 shrink-0 mt-0.5" />
        <p>
          Couldn't read the statement's balance summary, so these rows can't be checked automatically.
          Compare them against the PDF before applying.
        </p>
      </div>
    );
  }
  if (rec.difference_cents === 0) {
    return (
      <div className="mt-3 flex gap-2 rounded-lg border border-emerald-200 dark:border-emerald-800 bg-emerald-50 dark:bg-emerald-900/30 p-3 text-sm text-emerald-800 dark:text-emerald-300">
        <CheckCircle2 className="h-4 w-4 shrink-0 mt-0.5" />
        <p>
          Matches the statement: {formatCents(rec.previous_balance_cents ?? 0)} previous
          + {formatCents(rec.charges_cents)} charges − {formatCents(rec.credits_cents)} credits
          = {formatCents(rec.new_balance_cents ?? 0)} new balance.
        </p>
      </div>
    );
  }
  const missing = -rec.difference_cents;
  return (
    <div className="mt-3 flex gap-2 rounded-lg border border-amber-300 dark:border-amber-800 bg-amber-50 dark:bg-amber-900/30 p-3 text-sm text-amber-800 dark:text-amber-300">
      <AlertTriangle className="h-4 w-4 shrink-0 mt-0.5" />
      <div>
        <p className="font-medium">
          Doesn't add up: off by {formatCents(Math.abs(rec.difference_cents))}.
        </p>
        <p className="text-xs mt-1">
          Statement says {formatCents(rec.previous_balance_cents ?? 0)} →{" "}
          {formatCents(rec.new_balance_cents ?? 0)}, but these rows give{" "}
          {formatCents((rec.previous_balance_cents ?? 0) + rec.charges_cents - rec.credits_cents)}.{" "}
          {missing > 0
            ? "Likely a charge was missed or a credit was read twice."
            : "Likely a payment/credit was missed or a charge was read twice."}{" "}
          Check against the PDF: skip a bad row here, and add a missed one with + Add afterwards.
        </p>
      </div>
    </div>
  );
}
