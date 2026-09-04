import { ChevronLeft, ChevronRight } from "lucide-react";
import {
  currentMonth,
  formatMonthLabel,
  isFutureMonth,
  isCurrentMonth,
  nextMonth,
  prevMonth,
} from "../lib/month-utils";
import { cn } from "../lib/utils";

interface MonthSelectorProps {
  month: string;
  onChange: (month: string) => void;
  className?: string;
}

export function MonthSelector({ month, onChange, className }: MonthSelectorProps) {
  const disableNext = isFutureMonth(nextMonth(month));

  return (
    <div className={cn("inline-flex items-center gap-1", className)}>
      <button
        onClick={() => onChange(prevMonth(month))}
        className="p-1.5 rounded-md hover:bg-gray-100 dark:hover:bg-gray-700 text-gray-600 dark:text-gray-400 hover:text-gray-900 dark:hover:text-gray-200 transition-colors"
        title="Previous month"
      >
        <ChevronLeft className="h-4 w-4" />
      </button>
      <span className="text-sm font-medium text-gray-800 dark:text-gray-200 min-w-[120px] text-center select-none">
        {formatMonthLabel(month)}
      </span>
      <button
        onClick={() => !disableNext && onChange(nextMonth(month))}
        disabled={disableNext}
        className={cn(
          "p-1.5 rounded-md transition-colors",
          disableNext
            ? "text-gray-300 dark:text-gray-600 cursor-not-allowed"
            : "hover:bg-gray-100 dark:hover:bg-gray-700 text-gray-600 dark:text-gray-400 hover:text-gray-900 dark:hover:text-gray-200",
        )}
        title="Next month"
      >
        <ChevronRight className="h-4 w-4" />
      </button>
      {!isCurrentMonth(month) && (
        <button
          onClick={() => onChange(currentMonth())}
          className="ml-1 text-[10px] text-sky-600 dark:text-sky-400 hover:text-sky-800 dark:hover:text-sky-300 font-medium"
        >
          Today
        </button>
      )}
    </div>
  );
}
