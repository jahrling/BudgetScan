import { useState } from "react";
import { Layout } from "../components/Layout";
import { Button } from "../components/ui/button";
import { Label } from "../components/ui/label";
import { Input } from "../components/ui/input";
import { useAccounts } from "../hooks/useAccounts";

export default function ExportPage() {
  const { data: accounts = [] } = useAccounts();
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [selected, setSelected] = useState<Set<number>>(new Set());

  function toggle(id: number) {
    const next = new Set(selected);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    setSelected(next);
  }

  function download() {
    const params = new URLSearchParams();
    for (const id of selected) params.append("accounts", String(id));
    if (from) params.set("date_from", new Date(from).toISOString());
    if (to) params.set("date_to", new Date(to + "T23:59:59").toISOString());
    window.location.href = `/api/export/qif?${params.toString()}`;
  }

  return (
    <Layout>
      <h1 className="text-2xl font-semibold text-gray-900 dark:text-gray-100 mb-4">Export to Quicken</h1>

      <p className="text-sm text-gray-600 dark:text-gray-400 mb-4">
        Import this QIF into Quicken via{" "}
        <strong>File → File Import → QIF File</strong>. Choose &ldquo;all
        accounts&rdquo; and uncheck duplicates so the new splits replace the
        flat transactions Quicken already has.
      </p>

      <div className="space-y-3 mb-4">
        <div>
          <Label>From</Label>
          <Input
            type="date"
            value={from}
            onChange={(e) => setFrom(e.target.value)}
          />
        </div>
        <div>
          <Label>To</Label>
          <Input
            type="date"
            value={to}
            onChange={(e) => setTo(e.target.value)}
          />
        </div>
        <div>
          <Label>Accounts</Label>
          <div className="space-y-1 mt-1">
            {accounts.map((a) => (
              <label key={a.id} className="flex items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  checked={selected.has(a.id)}
                  onChange={() => toggle(a.id)}
                />
                {a.name}
                {a.quicken_id && (
                  <span className="text-xs text-gray-500">
                    ({a.quicken_id})
                  </span>
                )}
              </label>
            ))}
          </div>
        </div>
      </div>

      <Button onClick={download} disabled={selected.size === 0}>
        Download QIF
      </Button>
    </Layout>
  );
}
