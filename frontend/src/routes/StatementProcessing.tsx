import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { AlertTriangle, FileText, Loader2 } from "lucide-react";
import { Layout } from "../components/Layout";
import { Button } from "../components/ui/button";
import {
  statementImageUrl,
  useStatementScan,
  useReprocessScan,
} from "../hooks/useStatementScans";

const POLL_TIMEOUT_MS = 120_000;

function isPdf(scan: { original_filename: string }) {
  return scan.original_filename.toLowerCase().endsWith(".pdf");
}

function StatementPreview({ scan }: { scan: { id: number; original_filename: string } }) {
  if (isPdf(scan)) {
    return (
      <div className="flex flex-col items-center justify-center rounded-lg border border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-800 p-6 max-h-64 mx-auto">
        <FileText className="h-12 w-12 text-gray-400 mb-2" />
        <p className="text-sm text-gray-500 dark:text-gray-400">{scan.original_filename}</p>
      </div>
    );
  }
  return (
    <img
      src={statementImageUrl(scan.id)}
      alt="Statement"
      className="rounded-lg border border-gray-200 dark:border-gray-700 max-h-64 mx-auto"
    />
  );
}

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
    const err = scan.ocr_error || "Unknown error";
    let hint = "";
    if (err.includes("not found in Ollama")) {
      hint = "The configured vision model isn't pulled. Run the 'ollama pull' command shown above, then try again.";
    } else if (err.includes("Cannot connect to Ollama")) {
      hint = "The Ollama service isn't reachable. Make sure it's running and the backend can connect to it.";
    } else if (err.includes("timed out")) {
      hint = "The model may still be loading into GPU memory. Wait a moment and try again — the first request after a restart is usually the slowest.";
    } else if (err.includes("empty response") || err.includes("did not return valid JSON")) {
      hint = "The model couldn't extract structured data from this image. Try a clearer photo, or check that the configured model supports vision.";
    }

    return (
      <Layout>
        <div className="space-y-4">
          <div className="flex items-start gap-2 rounded-lg border border-red-200 dark:border-red-800 bg-red-50 dark:bg-red-900/30 p-3">
            <AlertTriangle className="h-5 w-5 text-red-500 shrink-0 mt-0.5" />
            <div className="text-sm space-y-1">
              <p className="font-semibold text-red-700 dark:text-red-300">
                Could not read statement
              </p>
              <p className="text-red-700 dark:text-red-400 font-mono text-xs break-all">
                {err}
              </p>
              {hint && (
                <p className="text-red-600 dark:text-red-300 mt-1">
                  {hint}
                </p>
              )}
            </div>
          </div>

          <StatementPreview scan={scan} />

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
        <div className="mb-4">
          <StatementPreview scan={scan} />
        </div>
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
