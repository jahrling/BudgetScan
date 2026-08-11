import { type ReactNode } from "react";
import { Link, useLocation } from "react-router-dom";
import { cn } from "../lib/utils";
import { Home, Tags, Wallet, Receipt, ArrowLeftRight, FileText } from "lucide-react";

const navItems = [
  { to: "/", label: "Home", icon: Home },
  { to: "/transactions", label: "Txns", icon: Receipt },
  { to: "/categories", label: "Categories", icon: Tags },
  { to: "/budgets", label: "Budgets", icon: Wallet },
  { to: "/sync", label: "Sync", icon: ArrowLeftRight },
  { to: "/docs", label: "Docs", icon: FileText },
] as const;

export function Layout({ children }: { children: ReactNode }) {
  const location = useLocation();

  return (
    <div className="min-h-screen bg-gray-50 md:flex">
      {/* Desktop sidebar */}
      <nav className="hidden md:flex md:flex-col md:w-48 lg:w-56 md:fixed md:inset-y-0 bg-white border-r border-gray-200">
        <div className="px-4 py-5">
          <span className="text-sm font-semibold text-gray-900">BudgetScan</span>
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
                    ? "bg-sky-50 text-sky-700 font-medium"
                    : "text-gray-600 hover:bg-gray-50 hover:text-gray-900",
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
      <main className="mx-auto max-w-lg px-4 py-6 pb-20 md:max-w-4xl md:ml-48 lg:ml-56 md:pb-6">
        {children}
      </main>

      {/* Mobile bottom tab bar */}
      <nav className="fixed bottom-0 left-0 right-0 bg-white border-t border-gray-200 safe-area-pb md:hidden">
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
                  active ? "text-sky-600" : "text-gray-500 hover:text-gray-700",
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
