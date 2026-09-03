import { useMemo, useState } from "react";
import { ChevronRight, Database, Pencil, Plus, Search, Trash2 } from "lucide-react";
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
      <ul className={cn(depth > 0 && "ml-4 border-l border-gray-200")}>
        {children.map((cat) => {
          const hasChildren = byParent.has(cat.id) &&
            (!matchingIds || (byParent.get(cat.id) ?? []).some((c) => matchingIds.has(c.id)));
          const isExpanded = matchingIds ? true : expanded.has(cat.id);
          const isDirectMatch = matchingIds && cat.name.toLowerCase().includes(search.trim().toLowerCase());

          return (
            <li key={cat.id}>
              <div className={cn(
                "flex items-center gap-1 py-2 px-2 hover:bg-gray-50 rounded-md group",
                isDirectMatch && "bg-sky-50",
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
                  "flex-1 text-sm font-medium truncate",
                  isDirectMatch && "text-sky-700",
                )}>
                  {cat.name}
                  {cat.source === "app" && (
                    <span className="ml-1.5 inline-flex items-center rounded bg-sky-100 px-1 py-0.5 text-[10px] font-medium text-sky-700 align-middle">
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
        <h1 className="text-xl font-bold">Categories</h1>
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
        <div className="bg-white rounded-lg border border-gray-200 p-2">
          {renderTree(null, 0)}
        </div>
      )}

      {/* Search index management */}
      <div className="mt-6 rounded-lg border border-gray-200 bg-white p-3">
        <div className="flex items-center justify-between">
          <div>
            <p className="text-sm font-medium text-gray-700">Search index</p>
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
