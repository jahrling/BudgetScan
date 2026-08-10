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
    <div className="min-h-screen bg-gray-50 pb-16">
      <main className="mx-auto max-w-lg px-4 py-6">{children}</main>

      <nav className="fixed bottom-0 left-0 right-0 bg-white border-t border-gray-200 safe-area-pb">
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
