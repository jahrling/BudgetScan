import { useState, useRef, useEffect } from "react";
import { useSearchMerchants, useCreateMerchant } from "../hooks/useMerchants";
import type { Merchant } from "../types/models";

interface MerchantComboboxProps {
  value: Merchant | null;
  onSelect: (merchant: Merchant | null) => void;
}

export function MerchantCombobox({ value, onSelect }: MerchantComboboxProps) {
  const [query, setQuery] = useState(value?.name ?? "");
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const { data: results = [] } = useSearchMerchants(query);
  const createMut = useCreateMerchant();

  useEffect(() => {
    setQuery(value?.name ?? "");
  }, [value]);

  useEffect(() => {
    function handleClick(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, []);

  async function handleCreate() {
    if (!query.trim()) return;
    const m = await createMut.mutateAsync({ name: query.trim() });
    onSelect(m);
    setOpen(false);
  }

  const exactMatch = results.some(
    (r) => r.normalized_name === query.trim().toLowerCase()
  );

  return (
    <div ref={ref} className="relative">
      <input
        type="text"
        value={query}
        onChange={(e) => {
          setQuery(e.target.value);
          setOpen(true);
          if (e.target.value === "") onSelect(null);
        }}
        onFocus={() => query.length > 0 && setOpen(true)}
        placeholder="Search or create merchant…"
        className="flex h-10 w-full rounded-md border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-800 px-3 py-2 text-sm text-gray-900 dark:text-gray-100 placeholder:text-gray-400 dark:placeholder:text-gray-500 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-500"
      />
      {open && (results.length > 0 || query.trim().length > 0) && (
        <div className="absolute z-20 mt-1 w-full rounded-md border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 shadow-lg max-h-48 overflow-y-auto">
          {results.map((m) => (
            <button
              key={m.id}
              type="button"
              className="w-full px-3 py-2 text-left text-sm text-gray-900 dark:text-gray-100 hover:bg-sky-50 dark:hover:bg-sky-900/30 active:bg-sky-100 dark:active:bg-sky-900/50"
              onClick={() => {
                onSelect(m);
                setQuery(m.name);
                setOpen(false);
              }}
            >
              {m.name}
            </button>
          ))}
          {!exactMatch && query.trim().length > 0 && (
            <button
              type="button"
              className="w-full px-3 py-2 text-left text-sm text-sky-600 dark:text-sky-400 font-medium hover:bg-sky-50 dark:hover:bg-sky-900/30 active:bg-sky-100 dark:active:bg-sky-900/50 border-t border-gray-100 dark:border-gray-700"
              onClick={handleCreate}
            >
              + Create "{query.trim()}"
            </button>
          )}
        </div>
      )}
    </div>
  );
}
