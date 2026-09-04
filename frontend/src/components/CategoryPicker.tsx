import { useState, useRef, useEffect, useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "../lib/api";
import type { Category } from "../types/models";
import { cn } from "../lib/utils";
import { ChevronDown, Search, X } from "lucide-react";

interface CategoryPickerProps {
  value: number | null;
  onValueChange: (id: number | null) => void;
  excludeId?: number;
  allowNone?: boolean;
  noneLabel?: string;
  className?: string;
}

interface FlatOption {
  id: number;
  name: string;
  depth: number;
  parentName: string | null;
  source: string;
}

function buildOptions(
  categories: Category[],
  excludeId?: number,
): FlatOption[] {
  const byParent = new Map<number | null, Category[]>();
  const byId = new Map<number, Category>();
  for (const c of categories) {
    byId.set(c.id, c);
    const key = c.parent_id;
    if (!byParent.has(key)) byParent.set(key, []);
    byParent.get(key)!.push(c);
  }

  const result: FlatOption[] = [];

  function walk(parentId: number | null, depth: number) {
    const children = byParent.get(parentId) ?? [];
    for (const c of children.sort((a, b) => a.name.localeCompare(b.name))) {
      if (c.id === excludeId) continue;
      const parent = c.parent_id != null ? byId.get(c.parent_id) : null;
      result.push({
        id: c.id,
        name: c.name,
        depth,
        parentName: parent?.name ?? null,
        source: c.source,
      });
      walk(c.id, depth + 1);
    }
  }

  walk(null, 0);
  return result;
}

export function CategoryPicker({
  value,
  onValueChange,
  excludeId,
  allowNone = false,
  noneLabel = "— None —",
  className,
}: CategoryPickerProps) {
  const { data: categories = [] } = useQuery({
    queryKey: ["categories"],
    queryFn: () => api.get<Category[]>("/categories"),
  });

  const options = useMemo(
    () => buildOptions(categories, excludeId),
    [categories, excludeId],
  );

  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);

  const selectedOption = options.find((o) => o.id === value) ?? null;

  useEffect(() => {
    if (open) {
      setTimeout(() => inputRef.current?.focus(), 50);
    } else {
      setSearch("");
    }
  }, [open]);

  const filtered = useMemo(() => {
    if (!search.trim()) return options;
    const q = search.toLowerCase();
    return options.filter(
      (o) =>
        o.name.toLowerCase().includes(q) ||
        (o.parentName && o.parentName.toLowerCase().includes(q)),
    );
  }, [options, search]);

  function select(id: number | null) {
    onValueChange(id);
    setOpen(false);
  }

  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        className={cn(
          "flex h-10 w-full items-center justify-between rounded-md border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-800 px-3 py-2 text-sm text-gray-900 dark:text-gray-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-500",
          !selectedOption && "text-gray-400 dark:text-gray-500",
          className,
        )}
      >
        <span className="truncate">
          {selectedOption ? (
            <>
              {selectedOption.name}
              {selectedOption.parentName && (
                <span className="text-gray-400 dark:text-gray-500 text-xs ml-1">
                  in {selectedOption.parentName}
                </span>
              )}
            </>
          ) : (
            "Select category…"
          )}
        </span>
        <ChevronDown className="h-4 w-4 shrink-0 text-gray-400" />
      </button>

      {open && (
        <div className="fixed inset-0 z-50 flex items-start justify-center pt-[8vh]">
          <div
            className="fixed inset-0 bg-black/50"
            onClick={() => setOpen(false)}
          />
          <div className="relative z-10 rounded-lg bg-white dark:bg-gray-800 shadow-xl max-w-lg w-[calc(100%-2rem)] max-h-[75vh] flex flex-col">
            <div className="flex items-center gap-2 p-3 border-b border-gray-200 dark:border-gray-700">
              <Search className="h-4 w-4 text-gray-400 dark:text-gray-500 shrink-0" />
              <input
                ref={inputRef}
                type="text"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Search categories…"
                className="flex-1 text-sm bg-transparent text-gray-900 dark:text-gray-100 placeholder:text-gray-400 dark:placeholder:text-gray-500 focus:outline-none"
              />
              {search && (
                <button
                  type="button"
                  onClick={() => setSearch("")}
                  className="text-gray-400 hover:text-gray-600 dark:hover:text-gray-300"
                >
                  <X className="h-4 w-4" />
                </button>
              )}
            </div>

            <div className="overflow-y-auto flex-1 py-1">
              {allowNone && !search.trim() && (
                <button
                  type="button"
                  className={cn(
                    "w-full px-4 py-2.5 text-left text-sm text-gray-900 dark:text-gray-100 hover:bg-sky-50 dark:hover:bg-sky-900/30 active:bg-sky-100 dark:active:bg-sky-900/50",
                    value === null && "bg-sky-50 dark:bg-sky-900/30 font-medium text-sky-700 dark:text-sky-300",
                  )}
                  onClick={() => select(null)}
                >
                  {noneLabel}
                </button>
              )}
              {filtered.map((o) => (
                <button
                  key={o.id}
                  type="button"
                  className={cn(
                    "w-full py-2.5 pr-4 text-left text-sm text-gray-900 dark:text-gray-100 hover:bg-sky-50 dark:hover:bg-sky-900/30 active:bg-sky-100 dark:active:bg-sky-900/50",
                    o.id === value && "bg-sky-50 dark:bg-sky-900/30 font-medium text-sky-700 dark:text-sky-300",
                  )}
                  style={{
                    paddingLeft: `${1 + (search.trim() ? 0 : o.depth) * 1.25}rem`,
                  }}
                  onClick={() => select(o.id)}
                >
                  <span>{o.name}</span>
                  {o.source === "app" && (
                    <span className="ml-1 inline-flex items-center rounded bg-sky-100 dark:bg-sky-900/40 px-1 py-0.5 text-[10px] font-medium text-sky-700 dark:text-sky-300 align-middle">
                      custom
                    </span>
                  )}
                  {o.parentName && (
                    <span className="ml-1.5 text-xs text-gray-400 dark:text-gray-500">
                      in {o.parentName}
                    </span>
                  )}
                </button>
              ))}
              {filtered.length === 0 && (
                <p className="px-4 py-3 text-sm text-gray-400 dark:text-gray-500">
                  No categories match &ldquo;{search}&rdquo;
                </p>
              )}
            </div>
          </div>
        </div>
      )}
    </>
  );
}
