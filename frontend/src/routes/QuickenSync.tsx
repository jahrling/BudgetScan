import { useCallback, useEffect, useRef, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import {
  ArrowDownToLine,
  ArrowUpFromLine,
  Download,
  Upload,
} from "lucide-react";
import { Layout } from "../components/Layout";
import { Button } from "../components/ui/button";
import { Label } from "../components/ui/label";
import { Input } from "../components/ui/input";
import { apiFetch } from "../lib/api";
import { useAccounts, useCreateAccount } from "../hooks/useAccounts";
import { usePendingFile } from "../components/GlobalDropZone";
import {
  CandidateReview,
  defaultActionFor,
  type ParseResult,
  type RowAction,
} from "../components/ImportCandidateReview";

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
      <h1 className="text-lg font-semibold text-gray-900 dark:text-gray-100 mb-3">Quicken sync</h1>
      <p className="text-sm text-gray-500 mb-4">
        Import QIF data from Quicken, export categorized splits back.
      </p>

      {/* Tab switcher */}
      <div className="flex rounded-lg border border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-800 p-0.5 mb-4">
        <button
          type="button"
          onClick={() => setActiveTab("import")}
          className={`flex-1 flex items-center justify-center gap-1.5 rounded-md py-2 text-sm font-medium transition-colors ${
            activeTab === "import"
              ? "bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-100 shadow-sm"
              : "text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-200"
          }`}
        >
          <ArrowDownToLine className="h-4 w-4" />
          Import QIF
        </button>
        <button
          type="button"
          onClick={() => setActiveTab("export")}
          className={`flex-1 flex items-center justify-center gap-1.5 rounded-md py-2 text-sm font-medium transition-colors ${
            activeTab === "export"
              ? "bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-100 shadow-sm"
              : "text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-200"
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

function formatFromName(name: string): "qif" {
  const lower = name.toLowerCase();
  if (!lower.endsWith(".qif")) {
    throw new Error("Only QIF files are able to be imported.");
  }
  return "qif";
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
      <p className="text-sm text-gray-600 dark:text-gray-400 mb-3">
        In Quicken: <strong>File → File Export → QIF</strong>, then
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
            ? "border-sky-400 bg-sky-50 dark:bg-sky-900/30"
            : "border-gray-300 dark:border-gray-600 hover:border-sky-400"
        }`}
      >
        <input
          ref={fileInputRef}
          type="file"
          accept=".qif"
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
            <p className="text-sm font-medium text-gray-900 dark:text-gray-100">
              {localDragging ? "Drop file here" : "Drag & drop a QIF file"}
            </p>
            <p className="mt-1 text-xs text-gray-500">or click to browse</p>
          </>
        )}
      </div>

      {uploadMut.isError && (
        <p className="text-red-600 text-sm mt-2">
          {uploadMut.error instanceof Error ? uploadMut.error.message : String(uploadMut.error)}
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
      <p className="text-sm text-gray-600 dark:text-gray-400 mb-3">
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
