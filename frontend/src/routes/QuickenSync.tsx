import { useCallback, useEffect, useRef, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import {
  ArrowDownToLine,
  ArrowUpFromLine,
  ChevronDown,
  ChevronUp,
  Download,
  Upload,
} from "lucide-react";
import { Layout } from "../components/Layout";
import { Button } from "../components/ui/button";
import { Select } from "../components/ui/select";
import { Label } from "../components/ui/label";
import { Input } from "../components/ui/input";
import { apiFetch } from "../lib/api";
import { useAccounts, useCreateAccount } from "../hooks/useAccounts";
import { formatCents } from "../components/MoneyInput";
import { usePendingFile } from "../components/GlobalDropZone";

// --- Import types ---

interface SplitCandidate {
  category_path: string;
  amount_cents: number;
  description: string | null;
}

interface Candidate {
  source_account_key: string;
  account_id: number | null;
  posted_at: string;
  amount_cents: number;
  description: string | null;
  quicken_id: string | null;
  currency: string | null;
  splits: SplitCandidate[];
  match_status: "new" | "duplicate" | "likely-duplicate" | "matched-receipt";
  match_transaction_id: number | null;
  match_description: string | null;
  match_amount_cents: number | null;
  match_posted_at: string | null;
  match_category_path: string | null;
}

interface RulePersistResult {
  created: number;
  updated: number;
  unchanged: number;
}

interface ParseResult {
  candidates: Candidate[];
  unmapped_accounts: string[];
  errors: string[];
  rule_persist_result: RulePersistResult | null;
}

type RowAction = "create" | "skip" | `merge-with:${number}` | `overwrite:${number}`;

function isTrueRepeat(c: Candidate): boolean {
  if (!c.match_transaction_id) return false;
  if (c.match_description !== null && c.description !== null
      && c.match_description === c.description
      && c.match_amount_cents === c.amount_cents) {
    return true;
  }
  return false;
}

function defaultActionFor(c: Candidate): RowAction {
  if (c.match_status === "duplicate" && c.match_transaction_id) return "skip";
  if (c.match_status === "likely-duplicate" && isTrueRepeat(c)) return "skip";
  if (c.match_status === "matched-receipt" && c.match_transaction_id)
    return `merge-with:${c.match_transaction_id}`;
  return "create";
}

// --- Component ---

export default function QuickenSync() {
  const [activeTab, setActiveTab] = useState<"import" | "export">("import");
  const [hasUnapplied, setHasUnapplied] = useState(false);

  useEffect(() => {
    if (!hasUnapplied) return;
    const handler = (e: BeforeUnloadEvent) => {
      e.preventDefault();
    };
    window.addEventListener("beforeunload", handler);
    return () => window.removeEventListener("beforeunload", handler);
  }, [hasUnapplied]);

  return (
    <Layout>
      <h1 className="text-lg font-semibold mb-3">Quicken sync</h1>
      <p className="text-sm text-gray-500 mb-4">
        Import bank data from Quicken, export categorized splits back.
      </p>

      {/* Tab switcher */}
      <div className="flex rounded-lg border border-gray-200 bg-gray-50 p-0.5 mb-4">
        <button
          type="button"
          onClick={() => setActiveTab("import")}
          className={`flex-1 flex items-center justify-center gap-1.5 rounded-md py-2 text-sm font-medium transition-colors ${
            activeTab === "import"
              ? "bg-white text-gray-900 shadow-sm"
              : "text-gray-500 hover:text-gray-700"
          }`}
        >
          <ArrowDownToLine className="h-4 w-4" />
          Import QFX
        </button>
        <button
          type="button"
          onClick={() => setActiveTab("export")}
          className={`flex-1 flex items-center justify-center gap-1.5 rounded-md py-2 text-sm font-medium transition-colors ${
            activeTab === "export"
              ? "bg-white text-gray-900 shadow-sm"
              : "text-gray-500 hover:text-gray-700"
          }`}
        >
          <ArrowUpFromLine className="h-4 w-4" />
          Export QIF
        </button>
      </div>

      {activeTab === "import" ? (
        <ImportSection onUnappliedChange={setHasUnapplied} />
      ) : (
        <ExportSection />
      )}
    </Layout>
  );
}

// --- Import section (extracted from Import.tsx) ---

function formatFromName(name: string): "qfx" | "qif" {
  return name.toLowerCase().endsWith(".qif") ? "qif" : "qfx";
}

function ImportSection({
  onUnappliedChange,
}: {
  onUnappliedChange: (v: boolean) => void;
}) {
  const qc = useQueryClient();
  const { data: accounts = [] } = useAccounts();
  const createAccount = useCreateAccount();
  const { pendingFile, consumeFile, resetDrag } = usePendingFile();

  const [parsed, setParsed] = useState<ParseResult | null>(null);
  const [actions, setActions] = useState<RowAction[]>([]);
  const [createMissing, setCreateMissing] = useState(true);
  const [localDragging, setLocalDragging] = useState(false);
  const [fileName, setFileName] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [confirmResult, setConfirmResult] = useState<{
    created_ids: number[];
    merged_ids: number[];
    overwritten_ids: number[];
    skipped: number;
    errors: string[];
  } | null>(null);

  useEffect(() => {
    const unapplied = parsed !== null && confirmResult === null;
    onUnappliedChange(unapplied);
  }, [parsed, confirmResult, onUnappliedChange]);

  const uploadMut = useMutation({
    mutationFn: async (file: File) => {
      const format = formatFromName(file.name);
      const form = new FormData();
      form.append("file", file);
      const res = await fetch(`/api/import/${format}`, {
        method: "POST",
        credentials: "include",
        body: form,
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      return (await res.json()) as ParseResult;
    },
    onSuccess: (data) => {
      setParsed(data);
      setActions(data.candidates.map(defaultActionFor));
      setConfirmResult(null);
    },
  });

  const handleFile = useCallback(
    (file: File) => {
      setFileName(file.name);
      uploadMut.mutate(file);
    },
    [uploadMut],
  );

  useEffect(() => {
    if (pendingFile) {
      const file = consumeFile();
      if (file) handleFile(file);
    }
  }, [pendingFile, consumeFile, handleFile]);

  const confirmMut = useMutation({
    mutationFn: async () => {
      if (!parsed) throw new Error("no parsed data");
      const body = {
        candidates: parsed.candidates.map(({ match_description, match_amount_cents, match_posted_at, match_category_path, ...c }) => c),
        actions: actions.map((a, i) => ({ candidate_index: i, action: a })),
        create_missing_categories: createMissing,
      };
      return apiFetch<{
        created_ids: number[];
        merged_ids: number[];
        overwritten_ids: number[];
        skipped: number;
        errors: string[];
      }>("/api/import/confirm", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
    },
    onSuccess: (data) => {
      setConfirmResult(data);
      if (data.errors.length === 0) {
        qc.invalidateQueries({ queryKey: ["transactions"] });
      }
    },
  });

  function onPick(e: React.ChangeEvent<HTMLInputElement>) {
    const f = e.target.files?.[0];
    if (f) handleFile(f);
    e.target.value = "";
  }

  async function mapUnmapped(key: string, accountId: number) {
    if (!parsed) return;
    const updated = {
      ...parsed,
      candidates: parsed.candidates.map((c) =>
        c.source_account_key === key ? { ...c, account_id: accountId } : c,
      ),
      unmapped_accounts: parsed.unmapped_accounts.filter((k) => k !== key),
    };
    setParsed(updated);
    await fetch(`/api/accounts/${accountId}`, {
      method: "PATCH",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ quicken_id: key }),
    });
    qc.invalidateQueries({ queryKey: ["accounts"] });
  }

  async function createAndMap(key: string) {
    const name = window.prompt(`Create a new account for "${key}"?`, key);
    if (!name) return;
    const acct = await createAccount.mutateAsync({ name, type: "checking" });
    await mapUnmapped(key, acct.id);
  }

  return (
    <div>
      <p className="text-sm text-gray-600 mb-3">
        In Quicken: <strong>File → File Export → QFX</strong> (or QIF), then
        drag-and-drop the file here — or click to browse.
      </p>

      <div
        onClick={() => fileInputRef.current?.click()}
        onDrop={(e) => {
          e.preventDefault();
          e.stopPropagation();
          setLocalDragging(false);
          resetDrag();
          const f = e.dataTransfer.files[0];
          if (f) handleFile(f);
        }}
        onDragOver={(e) => {
          e.preventDefault();
          e.stopPropagation();
          setLocalDragging(true);
        }}
        onDragLeave={(e) => {
          if (e.currentTarget.contains(e.relatedTarget as Node)) return;
          setLocalDragging(false);
        }}
        className={`mb-4 flex flex-col items-center justify-center rounded-lg border-2 border-dashed p-6 text-center cursor-pointer transition-colors ${
          localDragging
            ? "border-sky-400 bg-sky-50"
            : "border-gray-300 hover:border-sky-400"
        }`}
      >
        <input
          ref={fileInputRef}
          type="file"
          accept=".qfx,.ofx,.qif"
          onChange={onPick}
          className="hidden"
          disabled={uploadMut.isPending}
        />
        {uploadMut.isPending ? (
          <span className="inline-block h-3 w-3 rounded-sm bg-sky-500 mb-3 animate-pulse" />
        ) : (
          <Upload className={`h-8 w-8 mb-2 ${localDragging ? "text-sky-400" : "text-gray-400"}`} />
        )}
        {uploadMut.isPending ? (
          <p className="text-sm text-gray-500">Parsing{fileName ? ` ${fileName}` : ""}…</p>
        ) : (
          <>
            <p className="text-sm font-medium">
              {localDragging ? "Drop file here" : "Drag & drop a QFX or QIF file"}
            </p>
            <p className="mt-1 text-xs text-gray-500">or click to browse</p>
          </>
        )}
      </div>

      {uploadMut.isError && (
        <p className="text-red-600 text-sm mt-2">
          Upload failed: {String(uploadMut.error)}
        </p>
      )}

      {parsed && <CandidateReview
        parsed={parsed}
        setParsed={setParsed}
        actions={actions}
        setActions={setActions}
        createMissing={createMissing}
        setCreateMissing={setCreateMissing}
        confirmMut={confirmMut}
        confirmResult={confirmResult}
        accounts={accounts}
        mapUnmapped={mapUnmapped}
        createAndMap={createAndMap}
      />}
    </div>
  );
}

// --- Candidate review table ---

function CandidateReview({
  parsed,
  setParsed: _setParsed,
  actions,
  setActions,
  createMissing,
  setCreateMissing,
  confirmMut,
  confirmResult,
  accounts,
  mapUnmapped,
  createAndMap,
}: {
  parsed: ParseResult;
  setParsed: (p: ParseResult) => void;
  actions: RowAction[];
  setActions: (a: RowAction[]) => void;
  createMissing: boolean;
  setCreateMissing: (v: boolean) => void;
  confirmMut: ReturnType<typeof useMutation<any, any, void>>;
  confirmResult: {
    created_ids: number[];
    merged_ids: number[];
    overwritten_ids: number[];
    skipped: number;
    errors: string[];
  } | null;
  accounts: { id: number; name: string; quicken_id: string | null }[];
  mapUnmapped: (key: string, accountId: number) => void;
  createAndMap: (key: string) => void;
}) {
  const [expanded, setExpanded] = useState(true);

  return (
    <div className="mt-4 space-y-3">
      {parsed.rule_persist_result && (parsed.rule_persist_result.created > 0 || parsed.rule_persist_result.updated > 0) && (
        <div className="rounded-lg border border-sky-200 bg-sky-50 p-3 text-sm text-sky-800">
          <p className="font-medium">Memorized rules imported</p>
          <p className="text-xs mt-1 text-sky-700">
            {parsed.rule_persist_result.created > 0 && `${parsed.rule_persist_result.created} created`}
            {parsed.rule_persist_result.created > 0 && parsed.rule_persist_result.updated > 0 && ", "}
            {parsed.rule_persist_result.updated > 0 && `${parsed.rule_persist_result.updated} updated`}
            {parsed.rule_persist_result.unchanged > 0 && `, ${parsed.rule_persist_result.unchanged} unchanged`}
          </p>
        </div>
      )}

      {parsed.errors.length > 0 && (
        <div className="rounded-lg border border-red-300 bg-red-50 p-3 text-sm text-red-800">
          <p className="font-semibold mb-1">Errors:</p>
          <ul className="list-disc pl-4">
            {parsed.errors.map((e, i) => (
              <li key={i}>{e}</li>
            ))}
          </ul>
        </div>
      )}

      {parsed.unmapped_accounts.length > 0 && (
        <div className="rounded-lg border border-amber-300 bg-amber-50 p-3 text-sm">
          <p className="font-semibold mb-2">Unmapped accounts</p>
          {parsed.unmapped_accounts.map((key) => (
            <div key={key} className="flex flex-wrap items-center gap-2 mb-2">
              <code className="rounded bg-white px-2 py-1 text-xs">{key}</code>
              <Select
                onChange={(e) => {
                  const v = Number(e.target.value);
                  if (v) mapUnmapped(key, v);
                }}
                defaultValue=""
                className="flex-1 min-w-0"
              >
                <option value="" disabled>
                  Map to existing…
                </option>
                {accounts.map((a) => (
                  <option key={a.id} value={a.id}>
                    {a.name}
                  </option>
                ))}
              </Select>
              <Button size="sm" onClick={() => createAndMap(key)}>
                New
              </Button>
            </div>
          ))}
        </div>
      )}

      <div className="flex items-center gap-2">
        <input
          id="create-missing"
          type="checkbox"
          checked={createMissing}
          onChange={(e) => setCreateMissing(e.target.checked)}
        />
        <Label htmlFor="create-missing" className="text-xs">
          Auto-create categories not yet in BudgetScan
        </Label>
      </div>

      {(() => {
        const newCount = parsed.candidates.filter(c => c.match_status === "new").length;
        const dupCount = parsed.candidates.filter(c => c.match_status === "duplicate").length;
        const likelyDupCount = parsed.candidates.filter(c => c.match_status === "likely-duplicate").length;
        const autoSkipped = parsed.candidates.filter((c, i) => actions[i] === "skip" && c.match_status !== "new").length;
        return (
          <div className="rounded-md bg-gray-50 border border-gray-200 p-3 text-xs text-gray-700 space-y-1">
            <p className="font-medium text-sm text-gray-800">
              {parsed.candidates.length} transactions found
            </p>
            <p>
              {newCount > 0 && <span className="text-emerald-600 font-medium">{newCount} new</span>}
              {dupCount > 0 && <>{newCount > 0 && ", "}<span className="text-amber-600 font-medium">{dupCount} duplicate</span></>}
              {likelyDupCount > 0 && <>{(newCount > 0 || dupCount > 0) && ", "}<span className="text-orange-500 font-medium">{likelyDupCount} likely duplicate</span></>}
            </p>
            {autoSkipped > 0 && (
              <p className="text-gray-500">
                {autoSkipped} identical transactions will be skipped (same description, amount, date).
              </p>
            )}
          </div>
        );
      })()}

      <button
        type="button"
        onClick={() => setExpanded(!expanded)}
        className="flex w-full items-center justify-between text-sm font-medium text-gray-700 py-1"
      >
        <span>
          {expanded ? "Hide" : "Show"} transaction details
        </span>
        {expanded ? (
          <ChevronUp className="h-4 w-4" />
        ) : (
          <ChevronDown className="h-4 w-4" />
        )}
      </button>

      {expanded && (
        <div className="space-y-2 pb-2">
          {parsed.candidates.map((c, i) => (
            <div
              key={i}
              className={`rounded-lg border p-3 ${
                actions[i] === "skip"
                  ? "border-gray-200 bg-gray-50 opacity-60"
                  : c.match_status === "duplicate" || c.match_status === "likely-duplicate"
                    ? "border-amber-200 bg-amber-50/30"
                    : "border-gray-200 bg-white"
              }`}
            >
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0">
                  <div className="text-sm font-medium truncate">
                    {c.description || (
                      <span className="text-gray-400 italic">No description</span>
                    )}
                  </div>
                  <div className="text-xs text-gray-500">{c.posted_at.slice(0, 10)}</div>
                  {c.splits.length > 0 && (
                    <div className="text-xs text-gray-400 mt-1">
                      {c.splits.map((s, j) => (
                        <div key={j}>
                          {s.category_path} — {formatCents(s.amount_cents)}
                        </div>
                      ))}
                    </div>
                  )}
                </div>
                <div className="text-right shrink-0">
                  <div className="text-sm font-semibold tabular-nums">
                    {formatCents(c.amount_cents)}
                  </div>
                  <span
                    className={`text-xs ${
                      c.match_status === "duplicate"
                        ? "text-amber-600"
                        : c.match_status === "likely-duplicate"
                          ? "text-orange-500"
                          : c.match_status === "matched-receipt"
                            ? "text-sky-600"
                            : "text-emerald-600"
                    }`}
                  >
                    {c.match_status === "likely-duplicate"
                      ? isTrueRepeat(c) ? "exact match — skip" : "likely dup"
                      : c.match_status}
                  </span>
                </div>
              </div>

              {/* Comparison with existing transaction */}
              {c.match_transaction_id && c.match_description !== null && (
                <div className="mt-2 rounded border border-gray-200 bg-gray-50 p-2 text-xs">
                  <p className="font-medium text-gray-600 mb-1">
                    Existing #{c.match_transaction_id}:
                  </p>
                  <div className="flex justify-between gap-2">
                    <div className="min-w-0">
                      <p className={`truncate ${c.match_description !== c.description ? "text-orange-700 font-medium" : "text-gray-600"}`}>
                        {c.match_description}
                      </p>
                      {c.match_posted_at && (
                        <p className="text-gray-500">{c.match_posted_at.slice(0, 10)}</p>
                      )}
                      {c.match_category_path && (
                        <p className="text-sky-600">{c.match_category_path}</p>
                      )}
                    </div>
                    <div className="text-right shrink-0">
                      <p className={`font-semibold tabular-nums ${c.match_amount_cents !== c.amount_cents ? "text-orange-700" : "text-gray-600"}`}>
                        {c.match_amount_cents !== null ? formatCents(c.match_amount_cents) : "—"}
                      </p>
                    </div>
                  </div>
                </div>
              )}

              <div className="mt-2">
                <Select
                  value={actions[i] ?? "create"}
                  onChange={(e) => {
                    const next = [...actions];
                    next[i] = e.target.value as RowAction;
                    setActions(next);
                  }}
                  disabled={c.account_id === null}
                  className="h-8 text-xs"
                >
                  <option value="create">Create new</option>
                  <option value="skip">Skip</option>
                  {c.match_transaction_id && (
                    <>
                      <option value={`overwrite:${c.match_transaction_id}`}>
                        Overwrite #{c.match_transaction_id}
                      </option>
                      <option value={`merge-with:${c.match_transaction_id}`}>
                        Merge with #{c.match_transaction_id}
                      </option>
                    </>
                  )}
                </Select>
                {c.account_id === null && (
                  <p className="text-xs text-red-600 mt-1">Map account first</p>
                )}
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Sticky Apply bar — sits above bottom nav on mobile, bottom of content on desktop */}
      <div className="fixed bottom-16 left-0 right-0 z-10 bg-white/95 backdrop-blur border-t border-gray-200 px-4 py-3 md:sticky md:bottom-0 md:left-auto md:right-auto md:mt-2 md:rounded-lg md:border md:shadow-sm">
        <div className="mx-auto max-w-lg md:max-w-none">
          {confirmResult ? (
            <div className="text-sm">
              {confirmResult.errors.length === 0 ? (
                <div className="rounded-md bg-emerald-50 border border-emerald-200 p-3 text-center">
                  <p className="font-medium text-emerald-800">Import complete</p>
                  <p className="text-emerald-700 mt-1">
                    Created {confirmResult.created_ids.length}
                    {confirmResult.overwritten_ids.length > 0 && `, overwritten ${confirmResult.overwritten_ids.length}`}
                    , merged {confirmResult.merged_ids.length}
                    , skipped {confirmResult.skipped}.
                  </p>
                </div>
              ) : (
                <div className="rounded-md bg-red-50 border border-red-200 p-3">
                  <p className="font-medium text-red-800">Import finished with errors</p>
                  <p className="text-red-700 mt-1">
                    {confirmResult.errors.join("; ")}
                  </p>
                  {(confirmResult.created_ids.length > 0 || confirmResult.merged_ids.length > 0) && (
                    <p className="text-red-600 mt-1 text-xs">
                      ({confirmResult.created_ids.length} created, {confirmResult.merged_ids.length} merged, {confirmResult.skipped} skipped before error)
                    </p>
                  )}
                </div>
              )}
            </div>
          ) : confirmMut.isError ? (
            <div className="text-sm">
              <div className="rounded-md bg-red-50 border border-red-200 p-3">
                <p className="font-medium text-red-800">Apply failed</p>
                <p className="text-red-700 mt-1">{String(confirmMut.error)}</p>
              </div>
              <Button
                onClick={() => confirmMut.mutate()}
                disabled={confirmMut.isPending}
                className="w-full mt-2"
              >
                Retry
              </Button>
            </div>
          ) : (
            <Button
              onClick={() => confirmMut.mutate()}
              disabled={confirmMut.isPending || parsed.candidates.length === 0}
              className="w-full"
            >
              {confirmMut.isPending
                ? "Applying… please wait"
                : `Apply ${parsed.candidates.length} transactions`}
            </Button>
          )}
        </div>
      </div>
    </div>
  );
}

// --- Export section (extracted from Export.tsx) ---

function ExportSection() {
  const { data: accounts = [] } = useAccounts();
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [selected, setSelected] = useState<Set<number>>(new Set());

  function toggle(id: number) {
    const next = new Set(selected);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    setSelected(next);
  }

  function download() {
    const params = new URLSearchParams();
    for (const id of selected) params.append("accounts", String(id));
    if (from) params.set("date_from", new Date(from).toISOString());
    if (to) params.set("date_to", new Date(to + "T23:59:59").toISOString());
    window.location.href = `/api/export/qif?${params.toString()}`;
  }

  return (
    <div>
      <p className="text-sm text-gray-600 mb-3">
        Import the QIF into Quicken: <strong>File → File Import → QIF</strong>.
        Choose "all accounts" and uncheck duplicates.
      </p>

      <div className="space-y-3 mb-4">
        <div className="flex gap-3">
          <div className="flex-1">
            <Label className="text-xs text-gray-500">From</Label>
            <Input
              type="date"
              value={from}
              onChange={(e) => setFrom(e.target.value)}
              className="h-9 text-sm"
            />
          </div>
          <div className="flex-1">
            <Label className="text-xs text-gray-500">To</Label>
            <Input
              type="date"
              value={to}
              onChange={(e) => setTo(e.target.value)}
              className="h-9 text-sm"
            />
          </div>
        </div>
        <div>
          <Label className="text-xs text-gray-500">Accounts</Label>
          <div className="space-y-1 mt-1">
            {accounts.map((a) => (
              <label key={a.id} className="flex items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  checked={selected.has(a.id)}
                  onChange={() => toggle(a.id)}
                />
                {a.name}
                {a.quicken_id && (
                  <span className="text-xs text-gray-400">
                    ({a.quicken_id})
                  </span>
                )}
              </label>
            ))}
          </div>
        </div>
      </div>

      <Button
        onClick={download}
        disabled={selected.size === 0}
        className="w-full"
      >
        <Download className="h-4 w-4 mr-2" />
        Download QIF
      </Button>
    </div>
  );
}
