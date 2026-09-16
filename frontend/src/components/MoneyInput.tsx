import { forwardRef, type InputHTMLAttributes } from "react";
import { cn } from "../lib/utils";

interface MoneyInputProps
  extends Omit<InputHTMLAttributes<HTMLInputElement>, "value" | "onChange"> {
  /** Value in cents */
  valueCents: number | undefined;
  /** Called with new value in cents */
  onValueChange: (cents: number) => void;
}

export const MoneyInput = forwardRef<HTMLInputElement, MoneyInputProps>(
  ({ valueCents, onValueChange, className, onKeyDown, ...props }, ref) => {
    const cents = valueCents ?? 0;
    const display = (cents / 100).toFixed(2);

    function handleKeyDown(e: React.KeyboardEvent<HTMLInputElement>) {
      onKeyDown?.(e);
      if (e.defaultPrevented) return;

      if (e.key >= "0" && e.key <= "9") {
        e.preventDefault();
        onValueChange(cents * 10 + parseInt(e.key));
      } else if (e.key === "Backspace") {
        e.preventDefault();
        onValueChange(Math.floor(cents / 10));
      }
    }

    return (
      <div className="relative">
        <span className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400 dark:text-gray-500 text-sm">
          $
        </span>
        <input
          ref={ref}
          type="text"
          inputMode="numeric"
          value={display}
          onKeyDown={handleKeyDown}
          onChange={() => {}}
          className={cn(
            "flex h-10 w-full rounded-md border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-800 pl-7 pr-3 py-2 text-sm text-right text-gray-900 dark:text-gray-100 placeholder:text-gray-400 dark:placeholder:text-gray-500 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-500 disabled:cursor-not-allowed disabled:opacity-50",
            className,
          )}
          {...props}
        />
      </div>
    );
  },
);
MoneyInput.displayName = "MoneyInput";

export function formatCents(cents: number): string {
  return `$${(cents / 100).toFixed(2)}`;
}

const MICROS = 1_000_000;

export function formatShares(micros: number): string {
  if (micros % MICROS === 0) return (micros / MICROS).toFixed(0);
  if (micros % 10_000 === 0) return (micros / MICROS).toFixed(2);
  return (micros / MICROS).toFixed(4);
}

export function formatPrice(micros: number): string {
  return `$${(micros / MICROS).toFixed(2)}`;
}

export function formatPct(decimal: number): string {
  return `${(decimal * 100).toFixed(2)}%`;
}

export function formatGainCents(cents: number): string {
  const sign = cents > 0 ? "+" : cents < 0 ? "-" : "";
  return `${sign}${formatCents(Math.abs(cents))}`;
}

export function formatCentsCompact(cents: number): string {
  const abs = Math.abs(cents);
  const sign = cents < 0 ? "-" : "";
  if (abs >= 10_000_000) return `${sign}$${(abs / 100_000).toFixed(0)}K`;
  return `${sign}$${(abs / 100).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}
