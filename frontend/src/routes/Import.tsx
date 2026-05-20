import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Layout } from "../components/Layout";
import { Button } from "../components/ui/button";
import { Select } from "../components/ui/select";
import { Label } from "../components/ui/label";
import { Input } from "../components/ui/input";
import { apiFetch } from "../lib/api";
import { useAccounts, useCreateAccount } from "../hooks/useAccounts";
import { formatCents } from "../components/MoneyInput";

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
  if (c.match_status === "duplicate" && c.match_transaction_id) {
    return "skip";
  }
  if (c.match_status === "matched-receipt" && c.match_transaction_id) {
    return `merge-with:${c.match_transaction_id}`;
  }
  return "create";
}

export default function ImportPage() {
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
    // Patch the account to set quicken_id; user can then re-upload, OR we can
    // just rewrite the parsed candidates in-place to use this account.
    if (!parsed) return;
    const updated = {
      ...parsed,
      candidates: parsed.candidates.map((c) =>
        c.source_account_key === key ? { ...c, account_id: accountId } : c,
      ),
      unmapped_accounts: parsed.unmapped_accounts.filter((k) => k !== key),
    };
    setParsed(updated);
    // Also persist the quicken_id mapping for future imports.
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
    <Layout>
      <h1 className="text-2xl font-semibold mb-4">Import from Quicken</h1>

      <p className="text-sm text-gray-600 mb-4">
        In Quicken, choose <strong>File → File Export → QFX</strong> (or QIF)
        for the account and date range you want to bring in, then upload the
        file here.
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
        <Input
          type="file"
          accept=".qfx,.ofx,.qif,application/x-ofx,application/x-qif"
          onChange={onPick}
        />
      </div>

      {uploadMut.isPending && <p>Parsing…</p>}
      {uploadMut.isError && (
        <p className="text-red-600">Upload failed: {String(uploadMut.error)}</p>
      )}

      {parsed && (
        <>
          {parsed.errors.length > 0 && (
            <div className="mb-4 rounded border border-red-300 bg-red-50 p-3 text-sm text-red-800">
              <p className="font-semibold mb-1">Errors:</p>
              <ul className="list-disc pl-4">
                {parsed.errors.map((e, i) => (
                  <li key={i}>{e}</li>
                ))}
              </ul>
            </div>
          )}

          {parsed.unmapped_accounts.length > 0 && (
            <div className="mb-4 rounded border border-amber-300 bg-amber-50 p-3 text-sm">
              <p className="font-semibold mb-2">Unmapped accounts</p>
              {parsed.unmapped_accounts.map((key) => (
                <div key={key} className="flex items-center gap-2 mb-2">
                  <code className="rounded bg-white px-2 py-1 text-xs">{key}</code>
                  <Select
                    onChange={(e) => {
                      const v = Number(e.target.value);
                      if (v) mapUnmapped(key, v);
                    }}
                    defaultValue=""
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
                    Create new
                  </Button>
                </div>
              ))}
            </div>
          )}

          <div className="mb-3 flex items-center gap-2">
            <input
              id="create-missing"
              type="checkbox"
              checked={createMissing}
              onChange={(e) => setCreateMissing(e.target.checked)}
            />
            <Label htmlFor="create-missing">
              Create missing categories as flat paths
            </Label>
          </div>

          <table className="w-full text-sm border-collapse">
            <thead>
              <tr className="border-b text-left">
                <th className="py-2 pr-2">Date</th>
                <th className="py-2 pr-2">Description</th>
                <th className="py-2 pr-2 text-right">Amount</th>
                <th className="py-2 pr-2">Match</th>
                <th className="py-2 pr-2">Action</th>
              </tr>
            </thead>
            <tbody>
              {parsed.candidates.map((c, i) => (
                <tr key={i} className="border-b align-top">
                  <td className="py-2 pr-2 whitespace-nowrap">
                    {c.posted_at.slice(0, 10)}
                  </td>
                  <td className="py-2 pr-2">
                    {c.description || <em className="text-gray-400">(none)</em>}
                    {c.splits.length > 0 && (
                      <div className="text-xs text-gray-500 mt-1">
                        {c.splits.map((s, j) => (
                          <div key={j}>
                            {s.category_path} — {formatCents(s.amount_cents)}
                          </div>
                        ))}
                      </div>
                    )}
                  </td>
                  <td className="py-2 pr-2 text-right tabular-nums">
                    {formatCents(c.amount_cents)}
                  </td>
                  <td className="py-2 pr-2">
                    <span
                      className={
                        c.match_status === "duplicate"
                          ? "text-amber-700"
                          : c.match_status === "matched-receipt"
                            ? "text-sky-700"
                            : "text-emerald-700"
                      }
                    >
                      {c.match_status}
                    </span>
                  </td>
                  <td className="py-2 pr-2">
                    <Select
                      value={actions[i] ?? "create"}
                      onChange={(e) => {
                        const next = [...actions];
                        next[i] = e.target.value as RowAction;
                        setActions(next);
                      }}
                      disabled={c.account_id === null}
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
                      <p className="text-xs text-red-600 mt-1">
                        Map account first
                      </p>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>

          <div className="mt-4 flex items-center gap-3">
            <Button
              onClick={() => confirmMut.mutate()}
              disabled={confirmMut.isPending || parsed.candidates.length === 0}
            >
              {confirmMut.isPending ? "Applying…" : "Apply"}
            </Button>
            {confirmResult && (
              <div className="text-sm">
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
        </>
      )}
    </Layout>
  );
}
