import { type ReactNode } from "react";
import { Link, useLocation } from "react-router-dom";
import { cn } from "../lib/utils";
import { Home, Tags, Wallet, Receipt, ArrowLeftRight, FileText, BookOpen } from "lucide-react";

const navItems = [
  { to: "/", label: "Home", icon: Home },
  { to: "/transactions", label: "Txns", icon: Receipt },
  { to: "/categories", label: "Categories", icon: Tags },
  { to: "/budgets", label: "Budgets", icon: Wallet },
  { to: "/rules", label: "Rules", icon: BookOpen },
  { to: "/sync", label: "Sync", icon: ArrowLeftRight },
  { to: "/docs", label: "Docs", icon: FileText },
] as const;

export function Layout({ children, wide }: { children: ReactNode; wide?: boolean }) {
  const location = useLocation();

  return (
    <div className="min-h-screen bg-gray-50 dark:bg-gray-900 safe-area-pt md:flex">
      {/* Desktop sidebar */}
      <nav className="hidden md:flex md:flex-col md:w-48 lg:w-56 md:fixed md:inset-y-0 bg-white dark:bg-gray-800 border-r border-gray-200 dark:border-gray-700">
        <div className="px-4 py-5">
          <span className="text-sm font-semibold text-gray-900 dark:text-gray-100">BudgetScan</span>
        </div>
        <div className="flex-1 flex flex-col gap-0.5 px-2">
          {navItems.map(({ to, label, icon: Icon }) => {
            const active =
              to === "/" ? location.pathname === "/" : location.pathname.startsWith(to);
            return (
              <Link
                key={to}
                to={to}
                className={cn(
                  "flex items-center gap-3 rounded-lg px-3 py-2 text-sm transition-colors",
                  active
                    ? "bg-sky-50 dark:bg-sky-900/30 text-sky-700 dark:text-sky-300 font-medium"
                    : "text-gray-600 dark:text-gray-400 hover:bg-gray-50 dark:hover:bg-gray-700 hover:text-gray-900 dark:hover:text-gray-200",
                )}
              >
                <Icon className="h-4 w-4 shrink-0" />
                {label}
              </Link>
            );
          })}
        </div>
      </nav>

      {/* Main content — shifts right on desktop to clear the sidebar */}
      <main className={cn(
        "w-full mx-auto max-w-lg px-4 py-6 pb-20 md:ml-48 lg:ml-56 md:pb-6",
        wide ? "md:max-w-6xl" : "md:max-w-4xl",
      )}>
        {children}
      </main>

      {/* Mobile bottom tab bar */}
      <nav className="fixed bottom-0 left-0 right-0 bg-white dark:bg-gray-800 border-t border-gray-200 dark:border-gray-700 safe-area-pb md:hidden">
        <div className="mx-auto max-w-lg flex justify-around">
          {navItems.map(({ to, label, icon: Icon }) => {
            const active =
              to === "/" ? location.pathname === "/" : location.pathname.startsWith(to);
            return (
              <Link
                key={to}
                to={to}
                className={cn(
                  "flex flex-col items-center py-2 px-3 text-xs transition-colors",
                  active ? "text-sky-600 dark:text-sky-400" : "text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-300",
                )}
              >
                <Icon className="h-5 w-5 mb-0.5" />
                {label}
              </Link>
            );
          })}
        </div>
      </nav>
    </div>
  );
}
