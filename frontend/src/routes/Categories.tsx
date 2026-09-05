import { useMemo, useState } from "react";
import {
  Brain,
  ChevronRight,
  Database,
  Download,
  HelpCircle,
  Pencil,
  Play,
  Plus,
  Repeat,
  Search,
  Sparkles,
  Trash2,
  Wrench,
} from "lucide-react";
import { useMutation } from "@tanstack/react-query";
import { Layout } from "../components/Layout";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { Label } from "../components/ui/label";
import { Dialog, DialogTitle } from "../components/ui/dialog";
import { CategoryPicker } from "../components/CategoryPicker";
import {
  useCategories,
  useCreateCategory,
  useDeleteCategory,
  useUpdateCategory,
} from "../hooks/useCategories";
import {
  useGenerateDrafts,
  useRunMonthly,
  useSeedRules,
} from "../hooks/useRules";
import { useDetectRecurring, useGenerateRules } from "../hooks/useTransactions";
import { api } from "../lib/api";
import type { Category } from "../types/models";
import { cn } from "../lib/utils";

interface FormState {
  id?: number;
  name: string;
  parent_id: number | null;
}

const emptyForm: FormState = { name: "", parent_id: null };

export default function Categories() {
  const { data: categories = [], isLoading } = useCategories();
  const createMut = useCreateCategory();
  const updateMut = useUpdateCategory();
  const deleteMut = useDeleteCategory();

  const [modalOpen, setModalOpen] = useState(false);
  const [form, setForm] = useState<FormState>(emptyForm);
  const [expanded, setExpanded] = useState<Set<number>>(new Set());
  const [search, setSearch] = useState("");
  const reindexMut = useMutation({
    mutationFn: () => api.post<{ indexed: number }>("/rules/reindex", {}),
  });
  const [toolsOpen, setToolsOpen] = useState(false);

  const matchingIds = useMemo(() => {
    if (!search.trim()) return null;
    const q = search.trim().toLowerCase();
    const matched = new Set<number>();
    for (const c of categories) {
      if (c.name.toLowerCase().includes(q)) {
        matched.add(c.id);
        let pid = c.parent_id;
        while (pid !== null) {
          matched.add(pid);
          const parent = categories.find((p) => p.id === pid);
          pid = parent?.parent_id ?? null;
        }
      }
    }
    return matched;
  }, [categories, search]);

  function openCreate(parentId: number | null = null) {
    setForm({ name: "", parent_id: parentId });
    setModalOpen(true);
  }

  function openEdit(cat: Category) {
    setForm({ id: cat.id, name: cat.name, parent_id: cat.parent_id });
    setModalOpen(true);
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (form.id) {
      await updateMut.mutateAsync({
        id: form.id,
        name: form.name,
        parent_id: form.parent_id,
      });
    } else {
      await createMut.mutateAsync({
        name: form.name,
        parent_id: form.parent_id,
      });
    }
    setModalOpen(false);
    setForm(emptyForm);
  }

  async function handleDelete(id: number) {
    if (!confirm("Delete this category?")) return;
    await deleteMut.mutateAsync(id);
  }

  function toggleExpand(id: number) {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  const byParent = new Map<number | null, Category[]>();
  for (const c of categories) {
    const key = c.parent_id;
    if (!byParent.has(key)) byParent.set(key, []);
    byParent.get(key)!.push(c);
  }

  function renderTree(parentId: number | null, depth: number) {
    let children = (byParent.get(parentId) ?? []).sort((a, b) =>
      a.name.localeCompare(b.name),
    );
    if (matchingIds) {
      children = children.filter((c) => matchingIds.has(c.id));
    }
    if (!children.length) return null;

    return (
      <ul className={cn(depth > 0 && "ml-4 border-l border-gray-200 dark:border-gray-700")}>
        {children.map((cat) => {
          const hasChildren = byParent.has(cat.id) &&
            (!matchingIds || (byParent.get(cat.id) ?? []).some((c) => matchingIds.has(c.id)));
          const isExpanded = matchingIds ? true : expanded.has(cat.id);
          const isDirectMatch = matchingIds && cat.name.toLowerCase().includes(search.trim().toLowerCase());

          return (
            <li key={cat.id}>
              <div className={cn(
                "flex items-center gap-1 py-2 px-2 hover:bg-gray-50 dark:hover:bg-gray-700 rounded-md group",
                isDirectMatch && "bg-sky-50 dark:bg-sky-900/30",
              )}>
                <button
                  onClick={() => hasChildren && toggleExpand(cat.id)}
                  className="w-5 h-5 flex items-center justify-center shrink-0"
                >
                  {hasChildren && (
                    <ChevronRight
                      className={cn(
                        "h-4 w-4 text-gray-400 transition-transform",
                        isExpanded && "rotate-90",
                      )}
                    />
                  )}
                </button>

                <span className={cn(
                  "flex-1 text-sm font-medium truncate text-gray-900 dark:text-gray-100",
                  isDirectMatch && "text-sky-700 dark:text-sky-300",
                )}>
                  {cat.name}
                  {cat.source === "app" && (
                    <span className="ml-1.5 inline-flex items-center rounded bg-sky-100 dark:bg-sky-900/40 px-1 py-0.5 text-[10px] font-medium text-sky-700 dark:text-sky-300 align-middle">
                      custom
                    </span>
                  )}
                </span>

                <div className="flex gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                  <Button
                    variant="ghost"
                    size="icon"
                    className="h-7 w-7"
                    onClick={() => openCreate(cat.id)}
                    title="Add child"
                  >
                    <Plus className="h-3.5 w-3.5" />
                  </Button>
                  <Button
                    variant="ghost"
                    size="icon"
                    className="h-7 w-7"
                    onClick={() => openEdit(cat)}
                    title="Edit"
                  >
                    <Pencil className="h-3.5 w-3.5" />
                  </Button>
                  <Button
                    variant="ghost"
                    size="icon"
                    className="h-7 w-7 text-red-500 hover:text-red-700"
                    onClick={() => handleDelete(cat.id)}
                    title="Delete"
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </Button>
                </div>
              </div>

              {hasChildren && isExpanded && renderTree(cat.id, depth + 1)}
            </li>
          );
        })}
      </ul>
    );
  }

  return (
    <Layout>
      <div className="flex items-center justify-between mb-4">
        <h1 className="text-xl font-bold text-gray-900 dark:text-gray-100">Categories</h1>
        <Button size="sm" onClick={() => openCreate()}>
          <Plus className="h-4 w-4 mr-1" />
          Add
        </Button>
      </div>

      {!isLoading && categories.length > 0 && (
        <div className="relative mb-3">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-gray-400" />
          <Input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Filter categories…"
            className="pl-9"
          />
        </div>
      )}

      {isLoading ? (
        <p className="text-gray-500 text-sm">Loading…</p>
      ) : categories.length === 0 ? (
        <p className="text-gray-500 text-sm">
          No categories yet. Tap Add to create one.
        </p>
      ) : matchingIds !== null && matchingIds.size === 0 ? (
        <p className="text-gray-500 text-sm">No categories match "{search}".</p>
      ) : (
        <div className="bg-white dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700 p-2">
          {renderTree(null, 0)}
        </div>
      )}

      {/* Search index management */}
      <div className="mt-6 rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 p-3">
        <div className="flex items-center justify-between">
          <div>
            <p className="text-sm font-medium text-gray-700 dark:text-gray-300">Search index</p>
            <p className="text-xs text-gray-500">
              Rebuild the embedding index used for smart categorization
            </p>
          </div>
          <Button
            size="sm"
            variant="outline"
            onClick={() => reindexMut.mutate()}
            disabled={reindexMut.isPending}
          >
            <Database className="h-4 w-4 mr-1" />
            {reindexMut.isPending ? "Rebuilding…" : "Rebuild"}
          </Button>
        </div>
        {reindexMut.isSuccess && (
          <p className="text-xs text-emerald-600 mt-2">
            Indexed {reindexMut.data.indexed} rules
          </p>
        )}
        {reindexMut.isError && (
          <p className="text-xs text-red-600 mt-2">
            Failed to rebuild index. Is Ollama running?
          </p>
        )}
      </div>

      {/* Categorization Tools */}
      <div className="mt-3 rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 p-3">
        <div className="flex items-center justify-between">
          <div>
            <p className="text-sm font-medium text-gray-700 dark:text-gray-300">Categorization Tools</p>
            <p className="text-xs text-gray-500">
              Run analysis tools to create rules, detect patterns, and improve auto-categorization
            </p>
          </div>
          <Button
            size="sm"
            variant="outline"
            onClick={() => setToolsOpen(true)}
          >
            <Wrench className="h-4 w-4 mr-1" />
            Open Tools
          </Button>
        </div>
      </div>

      {toolsOpen && (
        <CategorizationToolsModal onClose={() => setToolsOpen(false)} />
      )}

      <Dialog open={modalOpen} onClose={() => setModalOpen(false)}>
        <DialogTitle>{form.id ? "Edit Category" : "New Category"}</DialogTitle>
        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <Label htmlFor="cat-name">Name</Label>
            <Input
              id="cat-name"
              value={form.name}
              onChange={(e) => setForm({ ...form, name: e.target.value })}
              required
              autoFocus
            />
          </div>
          <div>
            <Label htmlFor="cat-parent">Parent</Label>
            <CategoryPicker
              value={form.parent_id}
              onValueChange={(id) => setForm({ ...form, parent_id: id })}
              excludeId={form.id}
              allowNone
              noneLabel="— No parent (root) —"
            />
          </div>
          <div className="flex justify-end gap-2 pt-2">
            <Button
              type="button"
              variant="outline"
              onClick={() => setModalOpen(false)}
            >
              Cancel
            </Button>
            <Button
              type="submit"
              disabled={createMut.isPending || updateMut.isPending}
            >
              {form.id ? "Save" : "Create"}
            </Button>
          </div>
        </form>
      </Dialog>
    </Layout>
  );
}

const TOOL_HELP = {
  seed: {
    title: "Load Seed Rules",
    icon: Download,
    color: "text-sky-600 dark:text-sky-400",
    bgColor: "bg-sky-50 dark:bg-sky-900/20",
    borderColor: "border-sky-200 dark:border-sky-800",
    summary:
      "Loads a curated set of ~200+ common merchant-to-category mappings (Amazon → Shopping, Kroger → Groceries, Netflix → Streaming, etc.).",
    details:
      "These give BudgetScan a baseline for categorizing transactions before you've built up your own history. Seed rules have the lowest matching priority — your corrections and Quicken rules always win. Safe to run multiple times (idempotent).",
  },
  drafts: {
    title: "Generate Rules from History",
    icon: Sparkles,
    color: "text-amber-600 dark:text-amber-400",
    bgColor: "bg-amber-50 dark:bg-amber-900/20",
    borderColor: "border-amber-200 dark:border-amber-800",
    summary:
      "Scans your confirmed transactions for consistent categorization patterns.",
    details:
      "If you’ve categorized the same merchant the same way 2+ times, it suggests a rule so future transactions are auto-categorized. Suggestions appear as drafts on the Rules page for your review — nothing is auto-applied. Payees with conflicting categories are flagged as conflicts.",
  },
  ai: {
    title: "Generate Rules via AI",
    icon: Brain,
    color: "text-purple-600 dark:text-purple-400",
    bgColor: "bg-purple-50 dark:bg-purple-900/20",
    borderColor: "border-purple-200 dark:border-purple-800",
    summary:
      "Batches uncategorized transactions and asks the local AI model to suggest categorization rules.",
    details:
      "More efficient than categorizing one at a time — one AI call covers 10–20 similar transactions. Results appear as drafts on the Rules page. Requires Ollama to be running with the configured text model.",
  },
  recurring: {
    title: "Detect Recurring Transactions",
    icon: Repeat,
    color: "text-cyan-600 dark:text-cyan-400",
    bgColor: "bg-cyan-50 dark:bg-cyan-900/20",
    borderColor: "border-cyan-200 dark:border-cyan-800",
    summary:
      "Identifies transactions that repeat on a regular schedule — monthly subscriptions, weekly purchases, annual renewals.",
    details:
      "Flags them with a recurring badge and cadence (monthly/weekly/biweekly/annual) on the Transactions page. This is a tag, not a category — a transaction can be both “Groceries” and “recurring.” Works best with 3+ months of history. Each run recomputes from scratch.",
  },
} as const;

type ToolKey = keyof typeof TOOL_HELP;

function CategorizationToolsModal({ onClose }: { onClose: () => void }) {
  const seedMut = useSeedRules();
  const draftsMut = useGenerateDrafts();
  const aiMut = useGenerateRules();
  const recurringMut = useDetectRecurring();
  const runAllMut = useRunMonthly();

  const [expandedHelp, setExpandedHelp] = useState<Set<ToolKey>>(new Set());

  function toggleHelp(key: ToolKey) {
    setExpandedHelp((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }

  function seedResult() {
    if (!seedMut.isSuccess) return null;
    const d = seedMut.data;
    return `Loaded ${d.created} rule${d.created !== 1 ? "s" : ""} (${d.skipped} skipped${d.updated ? `, ${d.updated} updated` : ""})`;
  }

  function draftsResult() {
    if (!draftsMut.isSuccess) return null;
    const d = draftsMut.data;
    if (d.drafts_created === 0) return "No new patterns found.";
    return `Found ${d.drafts_created} new pattern${d.drafts_created !== 1 ? "s" : ""}. Review them on the Rules page.`;
  }

  function aiResult() {
    if (!aiMut.isSuccess) return null;
    const d = aiMut.data;
    if (d.drafts_created === 0) return "No new rules generated.";
    return `Created ${d.drafts_created} draft rule${d.drafts_created !== 1 ? "s" : ""} from ${d.transactions_covered} transactions.`;
  }

  function recurringResult() {
    if (!recurringMut.isSuccess) return null;
    const d = recurringMut.data;
    if (d.groups_found === 0) return "No recurring patterns found.";
    return `Found ${d.groups_found} recurring pattern${d.groups_found !== 1 ? "s" : ""} across ${d.transactions_flagged} transactions.`;
  }

  function runAllResult() {
    if (!runAllMut.isSuccess) return null;
    const d = runAllMut.data;
    const parts: string[] = [];
    if (d.seed.created > 0) parts.push(`${d.seed.created} seed rules`);
    if (d.drafts.drafts_created > 0) parts.push(`${d.drafts.drafts_created} draft rules`);
    if (d.recurring.groups_found > 0) parts.push(`${d.recurring.groups_found} recurring groups`);
    parts.push(`${d.reindex.indexed} rules indexed`);
    return parts.join(" · ");
  }

  const anyPending =
    seedMut.isPending || draftsMut.isPending || aiMut.isPending || recurringMut.isPending || runAllMut.isPending;

  return (
    <Dialog open onClose={onClose} className="max-w-lg">
      <DialogTitle>Categorization Tools</DialogTitle>
      <p className="text-xs text-gray-500 dark:text-gray-400 -mt-1 mb-3">
        Run these tools to improve auto-categorization. Individual tools can also be triggered via the monthly schedule.
      </p>

      <div className="space-y-3">
        {(Object.keys(TOOL_HELP) as ToolKey[]).map((key) => {
          const tool = TOOL_HELP[key];
          const Icon = tool.icon;
          const isExpanded = expandedHelp.has(key);

          const mut =
            key === "seed" ? seedMut :
            key === "drafts" ? draftsMut :
            key === "ai" ? aiMut :
            recurringMut;

          const resultText =
            key === "seed" ? seedResult() :
            key === "drafts" ? draftsResult() :
            key === "ai" ? aiResult() :
            recurringResult();

          const handleRun = () => {
            if (key === "seed") seedMut.mutate();
            else if (key === "drafts") draftsMut.mutate();
            else if (key === "ai") aiMut.mutate({});
            else recurringMut.mutate();
          };

          return (
            <div
              key={key}
              className={cn(
                "rounded-lg border p-3",
                tool.borderColor,
                tool.bgColor,
              )}
            >
              <div className="flex items-start justify-between gap-2">
                <div className="flex items-start gap-2 flex-1 min-w-0">
                  <Icon className={cn("h-5 w-5 mt-0.5 flex-shrink-0", tool.color)} />
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-medium text-gray-900 dark:text-gray-100">
                      {tool.title}
                    </p>
                    <p className="text-xs text-gray-600 dark:text-gray-400 mt-0.5">
                      {tool.summary}
                    </p>
                    {isExpanded && (
                      <p className="text-xs text-gray-500 dark:text-gray-400 mt-1.5 leading-relaxed">
                        {tool.details}
                      </p>
                    )}
                    <button
                      onClick={() => toggleHelp(key)}
                      className="inline-flex items-center gap-0.5 text-[11px] text-gray-400 hover:text-gray-600 dark:hover:text-gray-300 mt-1"
                    >
                      <HelpCircle className="h-3 w-3" />
                      {isExpanded ? "Less" : "Learn more"}
                    </button>
                  </div>
                </div>
                <Button
                  size="sm"
                  variant="outline"
                  onClick={handleRun}
                  disabled={mut.isPending || runAllMut.isPending}
                  className="flex-shrink-0"
                >
                  <Play className="h-3.5 w-3.5 mr-1" />
                  {mut.isPending ? "Running…" : "Run"}
                </Button>
              </div>

              {resultText && (
                <p className="text-xs text-emerald-700 dark:text-emerald-300 mt-2 ml-7">
                  {resultText}
                </p>
              )}
              {mut.isError && (
                <p className="text-xs text-red-600 dark:text-red-400 mt-2 ml-7">
                  Failed. {key === "ai" ? "Is Ollama running?" : "Check server logs."}
                </p>
              )}
            </div>
          );
        })}
      </div>

      {/* Run All */}
      <div className="mt-4 rounded-lg border border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-800 p-3">
        <div className="flex items-center justify-between">
          <div>
            <p className="text-sm font-medium text-gray-700 dark:text-gray-300">Run All</p>
            <p className="text-xs text-gray-500">
              Runs all four tools in sequence, plus rebuilds the search index
            </p>
          </div>
          <Button
            size="sm"
            onClick={() => runAllMut.mutate()}
            disabled={anyPending}
          >
            <Play className="h-3.5 w-3.5 mr-1" />
            {runAllMut.isPending ? "Running…" : "Run All"}
          </Button>
        </div>
        {runAllResult() && (
          <p className="text-xs text-emerald-700 dark:text-emerald-300 mt-2">
            {runAllResult()}
          </p>
        )}
        {runAllMut.isError && (
          <p className="text-xs text-red-600 dark:text-red-400 mt-2">
            Failed. Check server logs.
          </p>
        )}
      </div>

      <div className="flex justify-end mt-4">
        <Button variant="outline" onClick={onClose}>
          Close
        </Button>
      </div>
    </Dialog>
  );
}
