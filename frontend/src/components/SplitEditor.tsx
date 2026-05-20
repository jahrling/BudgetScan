import { Plus, Divide } from "lucide-react";
import { Button } from "./ui/button";
import { CategoryPicker } from "./CategoryPicker";
import { MoneyInput, formatCents } from "./MoneyInput";
import { Input } from "./ui/input";
import type { LineItemInput } from "../types/models";
import { cn } from "../lib/utils";

interface SplitEditorProps {
  totalCents: number;
  items: LineItemInput[];
  onChange: (items: LineItemInput[]) => void;
}

export function SplitEditor({ totalCents, items, onChange }: SplitEditorProps) {
  const allocated = items.reduce((s, i) => s + i.amount_cents, 0);
  const remaining = totalCents - allocated;

  function updateItem(idx: number, patch: Partial<LineItemInput>) {
    const next = items.map((item, i) =>
      i === idx ? { ...item, ...patch } : item
    );
    onChange(next);
  }

  function removeItem(idx: number) {
    onChange(items.filter((_, i) => i !== idx));
  }

  function addItem() {
    onChange([
      ...items,
      { category_id: 0, amount_cents: Math.max(remaining, 0), description: "" },
    ]);
  }

  function splitEvenly() {
    if (items.length < 2) return;
    const each = Math.floor(totalCents / items.length);
    const leftover = totalCents - each * items.length;
    const next = items.map((item, i) => ({
      ...item,
      amount_cents: each + (i === 0 ? leftover : 0),
    }));
    onChange(next);
  }

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <span className="text-sm font-medium text-gray-700">
          Total: {formatCents(totalCents)}
        </span>
        <span
          className={cn(
            "text-sm font-medium",
            remaining === 0
              ? "text-green-600"
              : remaining > 0
                ? "text-amber-600"
                : "text-red-600"
          )}
        >
          {remaining === 0
            ? "Balanced"
            : remaining > 0
              ? `${formatCents(remaining)} unallocated`
              : `${formatCents(Math.abs(remaining))} over`}
        </span>
      </div>

      {items.map((item, idx) => (
        <div
          key={idx}
          className="rounded-lg border border-gray-200 bg-white p-3 space-y-2"
        >
          <div className="flex items-center gap-2">
            <div className="flex-1 min-w-0">
              <CategoryPicker
                value={item.category_id || null}
                onValueChange={(id) =>
                  updateItem(idx, { category_id: id ?? 0 })
                }
              />
            </div>
            <div className="w-28 shrink-0">
              <MoneyInput
                valueCents={item.amount_cents}
                onValueChange={(cents) =>
                  updateItem(idx, { amount_cents: cents })
                }
              />
            </div>
          </div>
          <div className="flex items-center gap-2">
            <Input
              value={item.description ?? ""}
              onChange={(e) =>
                updateItem(idx, { description: e.target.value || null })
              }
              placeholder="Description (optional)"
              className="h-8 text-sm"
            />
            {items.length > 1 && (
              <button
                type="button"
                onClick={() => removeItem(idx)}
                className="shrink-0 text-red-400 hover:text-red-600 text-xs px-2 py-1"
              >
                Remove
              </button>
            )}
          </div>
        </div>
      ))}

      <div className="flex gap-2">
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={addItem}
          className="flex-1"
        >
          <Plus className="h-3.5 w-3.5 mr-1" />
          Add split
        </Button>
        {items.length >= 2 && (
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={splitEvenly}
            className="flex-1"
          >
            <Divide className="h-3.5 w-3.5 mr-1" />
            Split evenly
          </Button>
        )}
      </div>
    </div>
  );
}
