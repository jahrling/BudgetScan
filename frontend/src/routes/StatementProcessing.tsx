import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { AlertTriangle, Loader2 } from "lucide-react";
import { Layout } from "../components/Layout";
import { Button } from "../components/ui/button";
import {
  statementImageUrl,
  useStatementScan,
  useReprocessScan,
} from "../hooks/useStatementScans";

const POLL_TIMEOUT_MS = 120_000;

export default function StatementProcessing() {
  const { id } = useParams<{ id: string }>();
  const scanId = id ? Number(id) : null;
  const navigate = useNavigate();
  const { data: scan, refetch } = useStatementScan(scanId);
  const reprocess = useReprocessScan();

  const startedAt = useRef<number>(Date.now());
  const [timedOut, setTimedOut] = useState(false);

  useEffect(() => {
    if (!scan || scan.ocr_status !== "pending") return;
    const t = window.setTimeout(() => {
      if (scan.ocr_status === "pending") setTimedOut(true);
    }, POLL_TIMEOUT_MS - (Date.now() - startedAt.current));
    return () => window.clearTimeout(t);
  }, [scan]);

  useEffect(() => {
    if (!scan || !scanId) return;
    if (scan.ocr_status !== "done") return;
    navigate(`/statements/${scanId}/review`, { replace: true });
  }, [scan, scanId, navigate]);

  const elapsedSec = useMemo(
    () => Math.floor((Date.now() - startedAt.current) / 1000),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [scan?.updated_at],
  );

  if (!scanId) {
    return (
      <Layout>
        <p className="text-red-600">Bad URL.</p>
      </Layout>
    );
  }

  if (!scan) {
    return (
      <Layout>
        <div className="text-center py-12">
          <Loader2 className="h-6 w-6 mx-auto animate-spin text-gray-400" />
        </div>
      </Layout>
    );
  }

  if (scan.ocr_status === "failed") {
    return (
      <Layout>
        <div className="space-y-4">
          <div className="flex items-start gap-2 rounded-lg border border-red-200 dark:border-red-800 bg-red-50 dark:bg-red-900/30 p-3">
            <AlertTriangle className="h-5 w-5 text-red-500 shrink-0 mt-0.5" />
            <div className="text-sm">
              <p className="font-semibold text-red-700 dark:text-red-300">
                Could not read statement
              </p>
              <p className="text-red-700 dark:text-red-400">
                {scan.ocr_error || "Unknown error"}
              </p>
            </div>
          </div>

          <img
            src={statementImageUrl(scan.id)}
            alt="Statement"
            className="rounded-lg border border-gray-200 dark:border-gray-700 max-h-64 mx-auto"
          />

          <div className="flex gap-2">
            <Button
              variant="outline"
              className="flex-1"
              onClick={() =>
                reprocess.mutate(scan.id, { onSuccess: () => refetch() })
              }
              disabled={reprocess.isPending}
            >
              Try again
            </Button>
            <Button
              className="flex-1"
              onClick={() => navigate("/investments", { replace: true })}
            >
              Back to investments
            </Button>
          </div>
        </div>
      </Layout>
    );
  }

  return (
    <Layout>
      <div className="text-center">
        <img
          src={statementImageUrl(scan.id)}
          alt="Statement"
          className="rounded-lg border border-gray-200 dark:border-gray-700 max-h-72 mx-auto mb-4"
        />
        <div className="flex items-center justify-center gap-2 text-gray-600 dark:text-gray-400">
          <Loader2 className="h-5 w-5 animate-spin" />
          <span className="text-sm">Reading statement...</span>
        </div>
        <p className="text-xs text-gray-400 mt-1">{elapsedSec}s elapsed</p>

        {timedOut && (
          <div className="mt-6 space-y-2">
            <p className="text-sm text-amber-600">
              Still working? Statement OCR can take 30-60s. The model may be
              loading.
            </p>
            <div className="flex gap-2">
              <Button
                variant="outline"
                className="flex-1"
                onClick={() => {
                  setTimedOut(false);
                  startedAt.current = Date.now();
                  refetch();
                }}
              >
                Keep waiting
              </Button>
              <Button
                className="flex-1"
                onClick={() =>
                  navigate("/investments", { replace: true })
                }
              >
                Back to investments
              </Button>
            </div>
          </div>
        )}
      </div>
    </Layout>
  );
}
