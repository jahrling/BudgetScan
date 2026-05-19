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
  ({ valueCents, onValueChange, className, ...props }, ref) => {
    const dollars =
      valueCents !== undefined ? (valueCents / 100).toFixed(2) : "";

    return (
      <div className="relative">
        <span className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400 text-sm">
          $
        </span>
        <input
          ref={ref}
          type="number"
          step="0.01"
          min="0"
          value={dollars}
          onChange={(e) => {
            const val = parseFloat(e.target.value);
            if (!isNaN(val)) {
              onValueChange(Math.round(val * 100));
            } else if (e.target.value === "") {
              onValueChange(0);
            }
          }}
          className={cn(
            "flex h-10 w-full rounded-md border border-gray-300 bg-white pl-7 pr-3 py-2 text-sm placeholder:text-gray-400 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-500 disabled:cursor-not-allowed disabled:opacity-50",
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
