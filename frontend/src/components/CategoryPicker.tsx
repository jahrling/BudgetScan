import { forwardRef, type SelectHTMLAttributes } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "../lib/api";
import type { Category } from "../types/models";
import { cn } from "../lib/utils";

interface CategoryPickerProps
  extends Omit<SelectHTMLAttributes<HTMLSelectElement>, "value" | "onChange"> {
  value: number | null;
  onValueChange: (id: number | null) => void;
  excludeId?: number;
  allowNone?: boolean;
  noneLabel?: string;
}

function buildOptions(
  categories: Category[],
  excludeId?: number,
): { id: number; label: string; depth: number }[] {
  const byParent = new Map<number | null, Category[]>();
  for (const c of categories) {
    const key = c.parent_id;
    if (!byParent.has(key)) byParent.set(key, []);
    byParent.get(key)!.push(c);
  }

  const result: { id: number; label: string; depth: number }[] = [];

  function walk(parentId: number | null, depth: number) {
    const children = byParent.get(parentId) ?? [];
    for (const c of children.sort((a, b) => a.name.localeCompare(b.name))) {
      if (c.id === excludeId) continue;
      result.push({ id: c.id, label: "  ".repeat(depth) + c.name, depth });
      walk(c.id, depth + 1);
    }
  }

  walk(null, 0);
  return result;
}

export const CategoryPicker = forwardRef<HTMLSelectElement, CategoryPickerProps>(
  (
    {
      value,
      onValueChange,
      excludeId,
      allowNone = false,
      noneLabel = "— None —",
      className,
      ...props
    },
    ref,
  ) => {
    const { data: categories = [] } = useQuery({
      queryKey: ["categories"],
      queryFn: () => api.get<Category[]>("/categories"),
    });

    const options = buildOptions(categories, excludeId);

    return (
      <select
        ref={ref}
        value={value ?? ""}
        onChange={(e) => {
          const v = e.target.value;
          onValueChange(v === "" ? null : Number(v));
        }}
        className={cn(
          "flex h-10 w-full rounded-md border border-gray-300 bg-white px-3 py-2 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-500",
          className,
        )}
        {...props}
      >
        {allowNone && <option value="">{noneLabel}</option>}
        {!allowNone && !value && (
          <option value="" disabled>
            Select category…
          </option>
        )}
        {options.map((o) => (
          <option key={o.id} value={o.id}>
            {o.label}
          </option>
        ))}
      </select>
    );
  },
);
CategoryPicker.displayName = "CategoryPicker";
