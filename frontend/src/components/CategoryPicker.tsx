import { useState, useRef, useEffect, useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "../lib/api";
import type { Category } from "../types/models";
import { cn } from "../lib/utils";
import { ChevronDown } from "lucide-react";

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
  label: string;
  depth: number;
  parentName: string | null;
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
        label: "  ".repeat(depth) + c.name,
        depth,
        parentName: parent?.name ?? null,
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
  const ref = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const selectedOption = options.find((o) => o.id === value) ?? null;

  useEffect(() => {
    function handleClick(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false);
        setSearch("");
      }
    }
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, []);

  useEffect(() => {
    if (open) {
      inputRef.current?.focus();
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
    setSearch("");
  }

  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        onClick={() => setOpen(!open)}
        className={cn(
          "flex h-10 w-full items-center justify-between rounded-md border border-gray-300 bg-white px-3 py-2 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-500",
          !selectedOption && "text-gray-400",
          className,
        )}
      >
        <span className="truncate">
          {selectedOption ? selectedOption.name : "Select category…"}
        </span>
        <ChevronDown className="h-4 w-4 shrink-0 text-gray-400" />
      </button>

      {open && (
        <div className="absolute z-20 mt-1 w-full rounded-md border border-gray-200 bg-white shadow-lg">
          <div className="p-1.5">
            <input
              ref={inputRef}
              type="text"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search categories…"
              className="w-full rounded border border-gray-200 bg-gray-50 px-2 py-1.5 text-sm placeholder:text-gray-400 focus:outline-none focus:ring-1 focus:ring-sky-500"
            />
          </div>
          <div className="max-h-48 overflow-y-auto">
            {allowNone && (
              <button
                type="button"
                className={cn(
                  "w-full px-3 py-1.5 text-left text-sm hover:bg-sky-50 active:bg-sky-100",
                  value === null && "bg-sky-50 font-medium",
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
                  "w-full px-3 py-1.5 text-left text-sm hover:bg-sky-50 active:bg-sky-100",
                  o.id === value && "bg-sky-50 font-medium",
                )}
                onClick={() => select(o.id)}
              >
                {search.trim() ? (
                  <span>
                    {o.name}
                    {o.parentName && (
                      <span className="ml-1 text-gray-400">
                        in {o.parentName}
                      </span>
                    )}
                  </span>
                ) : (
                  o.label
                )}
              </button>
            ))}
            {filtered.length === 0 && (
              <p className="px-3 py-2 text-sm text-gray-400">No matches</p>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
