import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import {
  Check,
  ChevronDown,
  ChevronUp,
  FileText,
  Loader2,
  Plus,
  Trash2,
} from "lucide-react";
import { Layout } from "../components/Layout";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { Label } from "../components/ui/label";
import { Select } from "../components/ui/select";
import { MoneyInput, formatCents } from "../components/MoneyInput";
import {
  statementImageUrl,
  useStatementScan,
  useStatementPreview,
  useMaterializeStatement,
} from "../hooks/useStatementScans";
import { useAccounts } from "../hooks/useAccounts";
import type { StatementReviewPosition } from "../types/models";

const MICROS = 1_000_000;

interface EditablePosition extends StatementReviewPosition {
  user_modified: boolean;
}

function microsToDisplay(micros: number): string {
  const val = micros / MICROS;
  if (micros % MICROS === 0) return val.toFixed(0);
  if (micros % 10_000 === 0) return val.toFixed(2);
  return val.toFixed(6);
}

function parseMicros(s: string): number | null {
  const v = parseFloat(s);
  if (isNaN(v)) return null;
  return Math.round(v * MICROS);
}

export default function StatementReview() {
  const { id } = useParams<{ id: string }>();
  const scanId = id ? Number(id) : null;
  const navigate = useNavigate();
  const { data: scan } = useStatementScan(scanId);
  const { data: preview, isLoading, isError } = useStatementPreview(scanId);
  const scanIsPdf = scan?.original_filename?.toLowerCase().endsWith(".pdf") ?? false;
  const { data: accounts = [] } = useAccounts();
  const submit = useMaterializeStatement();

  const investmentAccounts = accounts.filter(
    (a) =>
      a.type === "brokerage" ||
      a.type === "ira" ||
      a.type === "401k" ||
      a.type === "roth_ira" ||
      a.type === "529" ||
      a.type === "hsa",
  );

  const [accountId, setAccountId] = useState<number | null>(null);
  const [asOf, setAsOf] = useState("");
  const [positions, setPositions] = useState<EditablePosition[]>([]);
  const [imageExpanded, setImageExpanded] = useState(false);
  const [initialized, setInitialized] = useState(false);

  useEffect(() => {
    if (accountId === null && investmentAccounts.length === 1) {
      setAccountId(investmentAccounts[0].id);
    }
  }, [investmentAccounts, accountId]);

  useEffect(() => {
    if (!preview || initialized) return;
    setAsOf(preview.statement_date || new Date().toISOString().slice(0, 10));
    setPositions(
      preview.positions.map((p) => ({ ...p, user_modified: false })),
    );
    setInitialized(true);
  }, [preview, initialized]);

  if (!scanId) {
    return (
      <Layout>
        <p className="text-red-600">Bad URL.</p>
      </Layout>
    );
  }

  if (isLoading || !preview) {
    return (
      <Layout>
        <div className="text-center py-12">
          <Loader2 className="h-6 w-6 mx-auto animate-spin text-gray-400" />
          <p className="text-sm text-gray-500 mt-2">Loading OCR results...</p>
        </div>
      </Layout>
    );
  }

  if (isError) {
    return (
      <Layout>
        <p className="text-red-600">Could not load statement preview.</p>
        <Button variant="outline" className="mt-4" onClick={() => navigate(-1)}>
          Go back
        </Button>
      </Layout>
    );
  }

  const totalMarketValue = positions.reduce(
    (s, p) => s + p.market_value_cents,
    0,
  );

  function updatePosition(idx: number, patch: Partial<EditablePosition>) {
    setPositions((prev) =>
      prev.map((p, i) => (i === idx ? { ...p, ...patch, user_modified: true } : p)),
    );
  }

  function removePosition(idx: number) {
    setPositions((prev) => prev.filter((_, i) => i !== idx));
  }

  function addPosition() {
    setPositions((prev) => [
      ...prev,
      {
        symbol: null,
        name: "",
        quantity_micros: 0,
        price_micros: null,
        market_value_cents: 0,
        cost_basis_cents: null,
        matched_security_id: null,
        matched_security_name: null,
        user_modified: true,
      },
    ]);
  }

  function handleSubmit() {
    if (!accountId || !asOf) return;
    submit.mutate(
      {
        scanId: scanId!,
        account_id: accountId,
        as_of: asOf,
        positions: positions.map((p) => ({
          security_id: p.matched_security_id,
          symbol: p.symbol,
          name: p.name,
          quantity_micros: p.quantity_micros,
          market_value_cents: p.market_value_cents,
          price_micros: p.price_micros,
          cost_basis_cents: p.cost_basis_cents,
        })),
      },
      {
        onSuccess: () => {
          navigate("/investments", { replace: true });
        },
      },
    );
  }

  return (
    <Layout wide>
      <div className="space-y-4 pb-4">
        <h1 className="text-lg font-semibold text-gray-900 dark:text-gray-100">
          Review statement
        </h1>

        {/* Statement preview */}
        <div>
          <button
            type="button"
            onClick={() => setImageExpanded(!imageExpanded)}
            className="w-full flex items-center justify-between text-sm text-gray-500 mb-1"
          >
            <span>Statement {scanIsPdf ? "file" : "image"}</span>
            {imageExpanded ? (
              <ChevronUp className="h-4 w-4" />
            ) : (
              <ChevronDown className="h-4 w-4" />
            )}
          </button>
          {scanIsPdf ? (
            <div className="flex flex-col items-center justify-center rounded-lg border border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-800 p-4 mx-auto">
              <FileText className="h-10 w-10 text-gray-400 mb-1" />
              <p className="text-sm text-gray-500 dark:text-gray-400">
                {scan?.original_filename}
              </p>
            </div>
          ) : (
            <img
              src={statementImageUrl(scanId)}
              alt="Statement"
              className={`rounded-lg border border-gray-200 dark:border-gray-700 mx-auto transition-all ${
                imageExpanded ? "max-h-[80vh]" : "max-h-32"
              }`}
            />
          )}
        </div>

        {/* Account & date */}
        <div className="rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 p-3 space-y-3">
          <div>
            <Label className="text-xs text-gray-500">Account</Label>
            <Select
              value={accountId ?? ""}
              onChange={(e) =>
                setAccountId(e.target.value ? Number(e.target.value) : null)
              }
            >
              <option value="" disabled>
                Select account...
              </option>
              {investmentAccounts.map((a) => (
                <option key={a.id} value={a.id}>
                  {a.name}
                </option>
              ))}
            </Select>
          </div>
          <div>
            <Label className="text-xs text-gray-500">Statement date</Label>
            <Input
              type="date"
              value={asOf}
              onChange={(e) => setAsOf(e.target.value)}
              className="h-9 text-sm"
            />
          </div>
          {preview.account_name && (
            <p className="text-xs text-gray-400">
              OCR detected: {preview.account_name}
            </p>
          )}
        </div>

        {/* Holdings table */}
        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <h2 className="text-sm font-semibold text-gray-700 dark:text-gray-300">
              Holdings ({positions.length})
            </h2>
            <span className="text-sm font-semibold text-gray-900 dark:text-gray-100">
              Total: {formatCents(totalMarketValue)}
            </span>
          </div>

          <div className="overflow-x-auto rounded-lg border border-gray-200 dark:border-gray-700">
            <table className="w-full text-sm">
              <thead>
                <tr className="bg-gray-50 dark:bg-gray-800 text-left text-xs text-gray-500 dark:text-gray-400">
                  <th className="px-2 py-1.5 font-medium">Security</th>
                  <th className="px-2 py-1.5 font-medium">Symbol</th>
                  <th className="px-2 py-1.5 font-medium text-right">Qty</th>
                  <th className="px-2 py-1.5 font-medium text-right">Price</th>
                  <th className="px-2 py-1.5 font-medium text-right">
                    Market Value
                  </th>
                  <th className="px-2 py-1.5 font-medium text-right">
                    Cost Basis
                  </th>
                  <th className="px-2 py-1.5 w-8"></th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100 dark:divide-gray-700">
                {positions.map((pos, idx) => (
                  <tr
                    key={idx}
                    className={
                      pos.user_modified
                        ? "bg-sky-50/50 dark:bg-sky-900/10"
                        : "bg-white dark:bg-gray-800"
                    }
                  >
                    <td className="px-2 py-1.5">
                      {pos.matched_security_id ? (
                        <span
                          className="text-gray-900 dark:text-gray-100"
                          title={`Matched: ${pos.matched_security_name}`}
                        >
                          {pos.matched_security_name || pos.name}
                        </span>
                      ) : (
                        <Input
                          value={pos.name}
                          onChange={(e) =>
                            updatePosition(idx, { name: e.target.value })
                          }
                          placeholder="Security name"
                          className="h-7 text-xs min-w-[120px]"
                        />
                      )}
                    </td>
                    <td className="px-2 py-1.5">
                      <Input
                        value={pos.symbol ?? ""}
                        onChange={(e) =>
                          updatePosition(idx, {
                            symbol: e.target.value || null,
                          })
                        }
                        placeholder="--"
                        className="h-7 text-xs w-16"
                      />
                    </td>
                    <td className="px-2 py-1.5">
                      <Input
                        type="text"
                        inputMode="decimal"
                        value={microsToDisplay(pos.quantity_micros)}
                        onChange={(e) => {
                          const m = parseMicros(e.target.value);
                          if (m !== null)
                            updatePosition(idx, { quantity_micros: m });
                        }}
                        className="h-7 text-xs text-right w-20"
                      />
                    </td>
                    <td className="px-2 py-1.5">
                      <Input
                        type="text"
                        inputMode="decimal"
                        value={
                          pos.price_micros !== null
                            ? (pos.price_micros / MICROS).toFixed(2)
                            : ""
                        }
                        onChange={(e) => {
                          if (e.target.value === "") {
                            updatePosition(idx, { price_micros: null });
                          } else {
                            const m = parseMicros(e.target.value);
                            if (m !== null)
                              updatePosition(idx, { price_micros: m });
                          }
                        }}
                        placeholder="--"
                        className="h-7 text-xs text-right w-20"
                      />
                    </td>
                    <td className="px-2 py-1.5">
                      <MoneyInput
                        valueCents={pos.market_value_cents}
                        onValueChange={(cents) =>
                          updatePosition(idx, { market_value_cents: cents })
                        }
                        className="h-7 text-xs w-24"
                      />
                    </td>
                    <td className="px-2 py-1.5">
                      {pos.cost_basis_cents !== null ? (
                        <MoneyInput
                          valueCents={pos.cost_basis_cents}
                          onValueChange={(cents) =>
                            updatePosition(idx, {
                              cost_basis_cents: cents || null,
                            })
                          }
                          className="h-7 text-xs w-24"
                        />
                      ) : (
                        <button
                          type="button"
                          onClick={() =>
                            updatePosition(idx, { cost_basis_cents: 0 })
                          }
                          className="h-7 w-24 text-xs text-gray-400 hover:text-gray-600 dark:hover:text-gray-300 border border-dashed border-gray-300 dark:border-gray-600 rounded-md"
                        >
                          --
                        </button>
                      )}
                    </td>
                    <td className="px-2 py-1.5">
                      <button
                        type="button"
                        onClick={() => removePosition(idx)}
                        className="p-0.5 text-gray-400 hover:text-red-500"
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={addPosition}
            className="w-full"
          >
            <Plus className="h-3.5 w-3.5 mr-1" />
            Add holding
          </Button>
        </div>

        {/* Submit */}
        <Button
          className="w-full"
          disabled={
            !accountId || !asOf || positions.length === 0 || submit.isPending
          }
          onClick={handleSubmit}
        >
          {submit.isPending ? (
            <>
              <Loader2 className="h-4 w-4 mr-2 animate-spin" />
              Saving...
            </>
          ) : (
            <>
              <Check className="h-4 w-4 mr-2" />
              Save {positions.length} snapshot{positions.length !== 1 ? "s" : ""}
            </>
          )}
        </Button>

        {submit.isError && (
          <p className="text-sm text-red-600 text-center">
            {(submit.error as Error).message}
          </p>
        )}
      </div>
    </Layout>
  );
}
