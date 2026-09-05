import { useState } from "react";
import { Search, Sparkles, Check, X, BookOpen } from "lucide-react";
import { Layout } from "../components/Layout";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { SegmentedControl } from "../components/ui/segmented-control";
import {
  useRules,
  useGenerateDrafts,
  useBulkActivateRules,
  useBulkDeleteRules,
  useUpdateRule,
} from "../hooks/useRules";
import type { Rule } from "../types/models";
import { cn } from "../lib/utils";

const SOURCE_LABELS: Record<string, { label: string; color: string }> = {
  user_created: { label: "User", color: "bg-sky-100 text-sky-700 dark:bg-sky-900 dark:text-sky-300" },
  qif_import: { label: "Quicken", color: "bg-violet-100 text-violet-700 dark:bg-violet-900 dark:text-violet-300" },
  seed: { label: "Seed", color: "bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-400" },
  auto_draft: { label: "Auto", color: "bg-amber-100 text-amber-700 dark:bg-amber-900 dark:text-amber-300" },
  llm_batch: { label: "AI", color: "bg-emerald-100 text-emerald-700 dark:bg-emerald-900 dark:text-emerald-300" },
};

function SourceBadge({ source }: { source: string }) {
  const info = SOURCE_LABELS[source] ?? { label: source, color: "bg-gray-100 text-gray-600" };
  return (
    <span className={cn("text-[10px] font-medium px-1.5 py-0.5 rounded", info.color)}>
      {info.label}
    </span>
  );
}

export default function Rules() {
  const [tab, setTab] = useState<"drafts" | "active" | "all">("drafts");
  const [search, setSearch] = useState("");
  const [selected, setSelected] = useState<Set<number>>(new Set());

  const statusFilter = tab === "drafts" ? "draft" : tab === "active" ? "active" : undefined;
  const { data, isLoading } = useRules({
    status: statusFilter,
    search: search || undefined,
  });
  const rules = data?.rules ?? [];

  const generateMut = useGenerateDrafts();
  const activateMut = useBulkActivateRules();
  const deleteMut = useBulkDeleteRules();
  const updateMut = useUpdateRule();

  function toggleSelected(id: number) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  function toggleAll() {
    if (selected.size === rules.length) {
      setSelected(new Set());
    } else {
      setSelected(new Set(rules.map((r) => r.id)));
    }
  }

  async function handleBulkActivate() {
    const ids = [...selected];
    await activateMut.mutateAsync(ids);
    setSelected(new Set());
  }

  async function handleBulkDelete() {
    const ids = [...selected];
    await deleteMut.mutateAsync(ids);
    setSelected(new Set());
  }

  return (
    <Layout>
      <div className="flex items-center justify-between mb-4">
        <h1 className="text-lg font-semibold text-gray-900 dark:text-gray-100 flex items-center gap-2">
          <BookOpen className="h-5 w-5" />
          Rules
        </h1>
        {tab === "drafts" && (
          <Button
            size="sm"
            onClick={() => generateMut.mutate()}
            disabled={generateMut.isPending}
          >
            <Sparkles className="h-4 w-4 mr-1" />
            {generateMut.isPending ? "Scanning..." : "Generate Drafts"}
          </Button>
        )}
      </div>

      {generateMut.isSuccess && (
        <div className="mb-3 text-sm text-emerald-600 dark:text-emerald-400 bg-emerald-50 dark:bg-emerald-900/30 rounded-md px-3 py-2">
          Found {generateMut.data.drafts_created} new patterns.
          {generateMut.data.skipped_existing > 0 && ` ${generateMut.data.skipped_existing} already covered.`}
          {generateMut.data.conflicts.length > 0 && ` ${generateMut.data.conflicts.length} conflicts skipped.`}
        </div>
      )}

      <div className="flex items-center gap-3 mb-4">
        <SegmentedControl
          value={tab}
          onChange={(v) => { setTab(v as typeof tab); setSelected(new Set()); }}
          options={[
            { value: "drafts", label: "Drafts" },
            { value: "active", label: "Active" },
            { value: "all", label: "All" },
          ]}
        />
        <div className="relative flex-1 max-w-xs">
          <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-4 w-4 text-gray-400" />
          <Input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search rules..."
            className="pl-8 h-8"
          />
        </div>
      </div>

      {tab === "drafts" && rules.length > 0 && (
        <div className="flex items-center gap-2 mb-3">
          <label className="flex items-center gap-1.5 text-sm text-gray-600 dark:text-gray-400 cursor-pointer">
            <input
              type="checkbox"
              checked={selected.size === rules.length && rules.length > 0}
              onChange={toggleAll}
              className="rounded border-gray-300 dark:border-gray-600"
            />
            Select all
          </label>
          {selected.size > 0 && (
            <>
              <Button
                size="sm"
                onClick={handleBulkActivate}
                disabled={activateMut.isPending}
              >
                <Check className="h-3.5 w-3.5 mr-1" />
                Approve ({selected.size})
              </Button>
              <Button
                size="sm"
                variant="outline"
                onClick={handleBulkDelete}
                disabled={deleteMut.isPending}
              >
                <X className="h-3.5 w-3.5 mr-1" />
                Dismiss ({selected.size})
              </Button>
            </>
          )}
        </div>
      )}

      {isLoading ? (
        <p className="text-gray-500 dark:text-gray-400 text-sm">Loading rules...</p>
      ) : rules.length === 0 ? (
        <div className="text-center py-12 text-gray-500 dark:text-gray-400">
          <p className="text-sm">
            {tab === "drafts"
              ? "No draft rules. Click \"Generate Drafts\" to scan your transaction history."
              : search
              ? `No rules matching "${search}".`
              : "No rules yet."}
          </p>
        </div>
      ) : (
        <div className="bg-white dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700 divide-y divide-gray-100 dark:divide-gray-700">
          {rules.map((rule) => (
            <RuleRow
              key={rule.id}
              rule={rule}
              selectable={tab === "drafts"}
              selected={selected.has(rule.id)}
              onToggle={() => toggleSelected(rule.id)}
              onActivate={
                rule.status === "draft"
                  ? () => updateMut.mutate({ id: rule.id, status: "active" })
                  : undefined
              }
              onDeactivate={
                rule.status === "active"
                  ? () => updateMut.mutate({ id: rule.id, status: "inactive" })
                  : undefined
              }
            />
          ))}
        </div>
      )}

      <p className="mt-3 text-xs text-gray-500 dark:text-gray-400">
        {data?.total ?? 0} rule{(data?.total ?? 0) !== 1 ? "s" : ""}
      </p>
    </Layout>
  );
}

function RuleRow({
  rule,
  selectable,
  selected,
  onToggle,
  onActivate,
  onDeactivate,
}: {
  rule: Rule;
  selectable: boolean;
  selected: boolean;
  onToggle: () => void;
  onActivate?: () => void;
  onDeactivate?: () => void;
}) {
  return (
    <div className="flex items-center gap-3 px-3 py-2.5">
      {selectable && (
        <input
          type="checkbox"
          checked={selected}
          onChange={onToggle}
          className="rounded border-gray-300 dark:border-gray-600 shrink-0"
        />
      )}
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2">
          <span className="text-sm font-medium text-gray-900 dark:text-gray-100 truncate">
            {rule.payee}
          </span>
          <SourceBadge source={rule.source} />
          {rule.status === "draft" && (
            <span className="text-[10px] font-medium px-1.5 py-0.5 rounded bg-amber-100 text-amber-700 dark:bg-amber-900 dark:text-amber-300">
              Draft
            </span>
          )}
        </div>
        <p className="text-xs text-gray-500 dark:text-gray-400 truncate">
          {rule.category_path || "No category"}
        </p>
      </div>
      <div className="flex items-center gap-1 shrink-0">
        {onActivate && (
          <Button size="sm" variant="outline" onClick={onActivate} className="h-7 px-2 text-xs">
            <Check className="h-3 w-3 mr-1" />
            Approve
          </Button>
        )}
        {onDeactivate && (
          <Button size="sm" variant="outline" onClick={onDeactivate} className="h-7 px-2 text-xs text-red-600 hover:text-red-700">
            <X className="h-3 w-3 mr-1" />
            Deactivate
          </Button>
        )}
      </div>
    </div>
  );
}
