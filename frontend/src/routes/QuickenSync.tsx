import { useState } from "react";
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
  match_status: "new" | "duplicate" | "matched-receipt";
  match_transaction_id: number | null;
}

interface ParseResult {
  candidates: Candidate[];
  unmapped_accounts: string[];
  errors: string[];
}

type RowAction = "create" | "skip" | `merge-with:${number}`;

function defaultActionFor(c: Candidate): RowAction {
  if (c.match_status === "duplicate" && c.match_transaction_id) return "skip";
  if (c.match_status === "matched-receipt" && c.match_transaction_id)
    return `merge-with:${c.match_transaction_id}`;
  return "create";
}

// --- Component ---

export default function QuickenSync() {
  const [activeTab, setActiveTab] = useState<"import" | "export">("import");

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

      {activeTab === "import" ? <ImportSection /> : <ExportSection />}
    </Layout>
  );
}

// --- Import section (extracted from Import.tsx) ---

function ImportSection() {
  const qc = useQueryClient();
  const { data: accounts = [] } = useAccounts();
  const createAccount = useCreateAccount();

  const [format, setFormat] = useState<"qfx" | "qif">("qfx");
  const [parsed, setParsed] = useState<ParseResult | null>(null);
  const [actions, setActions] = useState<RowAction[]>([]);
  const [createMissing, setCreateMissing] = useState(true);
  const [confirmResult, setConfirmResult] = useState<{
    created_ids: number[];
    merged_ids: number[];
    skipped: number;
    errors: string[];
  } | null>(null);

  const uploadMut = useMutation({
    mutationFn: async (file: File) => {
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

  const confirmMut = useMutation({
    mutationFn: async () => {
      if (!parsed) throw new Error("no parsed data");
      const body = {
        candidates: parsed.candidates,
        actions: actions.map((a, i) => ({ candidate_index: i, action: a })),
        create_missing_categories: createMissing,
      };
      return apiFetch<{
        created_ids: number[];
        merged_ids: number[];
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
    if (f) uploadMut.mutate(f);
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
        upload the file here.
      </p>

      <div className="flex items-center gap-3 mb-4">
        <Label>Format</Label>
        <Select
          value={format}
          onChange={(e) => setFormat(e.target.value as "qfx" | "qif")}
          className="w-24"
        >
          <option value="qfx">QFX</option>
          <option value="qif">QIF</option>
        </Select>
      </div>

      <label className="flex items-center gap-2 rounded-lg border-2 border-dashed border-gray-300 bg-white p-4 cursor-pointer hover:border-sky-400 transition-colors">
        <Upload className="h-5 w-5 text-gray-400 shrink-0" />
        <span className="text-sm text-gray-600">
          {uploadMut.isPending ? "Parsing…" : "Choose QFX or QIF file"}
        </span>
        <input
          type="file"
          accept=".qfx,.ofx,.qif,application/x-ofx,application/x-qif"
          onChange={onPick}
          className="hidden"
          disabled={uploadMut.isPending}
        />
      </label>

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
          Create missing categories as flat paths
        </Label>
      </div>

      <button
        type="button"
        onClick={() => setExpanded(!expanded)}
        className="flex w-full items-center justify-between text-sm font-medium text-gray-700 py-1"
      >
        <span>
          {parsed.candidates.length} transactions found
        </span>
        {expanded ? (
          <ChevronUp className="h-4 w-4" />
        ) : (
          <ChevronDown className="h-4 w-4" />
        )}
      </button>

      {expanded && (
        <div className="space-y-2">
          {parsed.candidates.map((c, i) => (
            <div
              key={i}
              className="rounded-lg border border-gray-200 bg-white p-3"
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
                        : c.match_status === "matched-receipt"
                          ? "text-sky-600"
                          : "text-emerald-600"
                    }`}
                  >
                    {c.match_status}
                  </span>
                </div>
              </div>
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
                  <option value="create">Create</option>
                  <option value="skip">Skip</option>
                  {c.match_transaction_id && (
                    <option value={`merge-with:${c.match_transaction_id}`}>
                      Merge with #{c.match_transaction_id}
                    </option>
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

      <div className="flex items-center gap-3">
        <Button
          onClick={() => confirmMut.mutate()}
          disabled={confirmMut.isPending || parsed.candidates.length === 0}
          className="flex-1"
        >
          {confirmMut.isPending ? "Applying…" : "Apply"}
        </Button>
      </div>
      {confirmResult && (
        <div className="text-sm text-center">
          {confirmResult.errors.length === 0 ? (
            <span className="text-emerald-700">
              Created {confirmResult.created_ids.length}, merged{" "}
              {confirmResult.merged_ids.length}, skipped{" "}
              {confirmResult.skipped}.
            </span>
          ) : (
            <span className="text-red-700">
              Errors: {confirmResult.errors.join("; ")}
            </span>
          )}
        </div>
      )}
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
