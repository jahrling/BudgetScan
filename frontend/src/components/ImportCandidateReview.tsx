import { useState } from "react";
import type { useMutation } from "@tanstack/react-query";
import { ChevronDown, ChevronUp } from "lucide-react";
import { Button } from "./ui/button";
import { Select } from "./ui/select";
import { Label } from "./ui/label";
import { formatCents } from "./MoneyInput";

// Shared review UI for imported transactions (Quicken sync + statement upload).

// --- Import types ---

export interface SplitCandidate {
  category_path: string;
  amount_cents: number;
  description: string | null;
}

export interface Candidate {
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

export interface RulePersistResult {
  created: number;
  updated: number;
  unchanged: number;
}

export interface ParseResult {
  candidates: Candidate[];
  unmapped_accounts: string[];
  errors: string[];
  rule_persist_result: RulePersistResult | null;
}

export type RowAction = "create" | "skip" | `merge-with:${number}` | `overwrite:${number}`;

export function isTrueRepeat(c: Candidate): boolean {
  if (!c.match_transaction_id) return false;
  if (c.match_description !== null && c.description !== null
      && c.match_description === c.description
      && c.match_amount_cents === c.amount_cents) {
    return true;
  }
  return false;
}

export function defaultActionFor(c: Candidate): RowAction {
  if (c.match_status === "duplicate" && c.match_transaction_id) return "skip";
  if (c.match_status === "likely-duplicate" && isTrueRepeat(c)) return "skip";
  if (c.match_status === "matched-receipt" && c.match_transaction_id)
    return `merge-with:${c.match_transaction_id}`;
  return "create";
}

// --- Candidate review table ---

export function CandidateReview({
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
  inDialog = false,
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
  mapUnmapped?: (key: string, accountId: number) => void;
  createAndMap?: (key: string) => void;
  /** Stick the Apply bar to the bottom of a scrolling Dialog instead of the viewport. */
  inDialog?: boolean;
}) {
  const [expanded, setExpanded] = useState(true);

  return (
    <div className="mt-4 space-y-3">
      {parsed.rule_persist_result && (parsed.rule_persist_result.created > 0 || parsed.rule_persist_result.updated > 0) && (
        <div className="rounded-lg border border-sky-200 dark:border-sky-800 bg-sky-50 dark:bg-sky-900/30 p-3 text-sm text-sky-800 dark:text-sky-300">
          <p className="font-medium">Memorized rules imported</p>
          <p className="text-xs mt-1 text-sky-700 dark:text-sky-400">
            {parsed.rule_persist_result.created > 0 && `${parsed.rule_persist_result.created} created`}
            {parsed.rule_persist_result.created > 0 && parsed.rule_persist_result.updated > 0 && ", "}
            {parsed.rule_persist_result.updated > 0 && `${parsed.rule_persist_result.updated} updated`}
            {parsed.rule_persist_result.unchanged > 0 && `, ${parsed.rule_persist_result.unchanged} unchanged`}
          </p>
        </div>
      )}

      {parsed.errors.length > 0 && (
        <div className="rounded-lg border border-red-300 dark:border-red-800 bg-red-50 dark:bg-red-900/30 p-3 text-sm text-red-800 dark:text-red-300">
          <p className="font-semibold mb-1">Errors:</p>
          <ul className="list-disc pl-4">
            {parsed.errors.map((e, i) => (
              <li key={i}>{e}</li>
            ))}
          </ul>
        </div>
      )}

      {parsed.unmapped_accounts.length > 0 && mapUnmapped && createAndMap && (
        <div className="rounded-lg border border-amber-300 dark:border-amber-800 bg-amber-50 dark:bg-amber-900/30 p-3 text-sm">
          <p className="font-semibold mb-2">Unmapped accounts</p>
          {parsed.unmapped_accounts.map((key) => (
            <div key={key} className="flex flex-wrap items-center gap-2 mb-2">
              <code className="rounded bg-white dark:bg-gray-800 px-2 py-1 text-xs">{key}</code>
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

      {parsed.candidates.some((c) => c.splits.length > 0) && (
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
      )}

      {(() => {
        const newCount = parsed.candidates.filter(c => c.match_status === "new").length;
        const dupCount = parsed.candidates.filter(c => c.match_status === "duplicate").length;
        const likelyDupCount = parsed.candidates.filter(c => c.match_status === "likely-duplicate").length;
        const autoSkipped = parsed.candidates.filter((c, i) => actions[i] === "skip" && c.match_status !== "new").length;
        return (
          <div className="rounded-md bg-gray-50 dark:bg-gray-800 border border-gray-200 dark:border-gray-700 p-3 text-xs text-gray-700 dark:text-gray-300 space-y-1">
            <p className="font-medium text-sm text-gray-800 dark:text-gray-200">
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
        className="flex w-full items-center justify-between text-sm font-medium text-gray-700 dark:text-gray-300 py-1"
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
                  ? "border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-800 opacity-60"
                  : c.match_status === "duplicate" || c.match_status === "likely-duplicate"
                    ? "border-amber-200 dark:border-amber-800 bg-amber-50/30 dark:bg-amber-900/20"
                    : "border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800"
              }`}
            >
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0">
                  <div className="text-sm font-medium truncate text-gray-900 dark:text-gray-100">
                    {c.description || (
                      <span className="text-gray-400 dark:text-gray-500 italic">No description</span>
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
                  <div className="text-sm font-semibold tabular-nums text-gray-900 dark:text-gray-100">
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
                <div className="mt-2 rounded border border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-800 p-2 text-xs">
                  <p className="font-medium text-gray-600 dark:text-gray-400 mb-1">
                    Existing #{c.match_transaction_id}:
                  </p>
                  <div className="flex justify-between gap-2">
                    <div className="min-w-0">
                      <p className={`truncate ${c.match_description !== c.description ? "text-orange-700 dark:text-orange-400 font-medium" : "text-gray-600 dark:text-gray-400"}`}>
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
                      <p className={`font-semibold tabular-nums ${c.match_amount_cents !== c.amount_cents ? "text-orange-700 dark:text-orange-400" : "text-gray-600 dark:text-gray-400"}`}>
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
      <div className={inDialog
        ? "sticky -bottom-6 -mx-6 z-10 bg-white/95 dark:bg-gray-800/95 backdrop-blur border-t border-gray-200 dark:border-gray-700 px-6 py-3"
        : "fixed bottom-16 left-0 right-0 z-10 bg-white/95 dark:bg-gray-900/95 backdrop-blur border-t border-gray-200 dark:border-gray-700 px-4 py-3 md:sticky md:bottom-0 md:left-auto md:right-auto md:mt-2 md:rounded-lg md:border md:shadow-sm"}>
        <div className="mx-auto max-w-lg md:max-w-none">
          {confirmResult ? (
            <div className="text-sm">
              {confirmResult.errors.length === 0 ? (
                <div className="rounded-md bg-emerald-50 dark:bg-emerald-900/30 border border-emerald-200 dark:border-emerald-800 p-3 text-center">
                  <p className="font-medium text-emerald-800 dark:text-emerald-300">Apply complete</p>
                  <p className="text-emerald-700 dark:text-emerald-400 mt-1">
                    Created {confirmResult.created_ids.length}
                    {confirmResult.overwritten_ids.length > 0 && `, overwritten ${confirmResult.overwritten_ids.length}`}
                    , merged {confirmResult.merged_ids.length}
                    , skipped {confirmResult.skipped}.
                  </p>
                </div>
              ) : (
                <div className="rounded-md bg-red-50 dark:bg-red-900/30 border border-red-200 dark:border-red-800 p-3">
                  <p className="font-medium text-red-800 dark:text-red-300">Apply finished with errors</p>
                  <p className="text-red-700 dark:text-red-400 mt-1">
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
              <div className="rounded-md bg-red-50 dark:bg-red-900/30 border border-red-200 dark:border-red-800 p-3">
                <p className="font-medium text-red-800 dark:text-red-300">Apply failed</p>
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
