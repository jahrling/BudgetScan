import { useRef, useState } from "react";
import { Camera, Loader2 } from "lucide-react";
import { useNavigate } from "react-router-dom";
import { Button } from "./ui/button";
import { uploadReceipt } from "../hooks/useReceipts";
import { ApiError } from "../lib/api";

interface Props {
  label?: string;
  variant?: "default" | "outline";
  className?: string;
  fab?: boolean;
}

/**
 * Renders a button that opens the iPhone camera (or file picker on desktop)
 * via a hidden <input type="file" accept="image/*" capture="environment">.
 *
 * On upload completion, navigates to `/receipts/<id>/processing`.
 */
export function SnapReceiptButton({
  label = "Snap receipt",
  variant = "default",
  className,
  fab = false,
}: Props) {
  const inputRef = useRef<HTMLInputElement>(null);
  const navigate = useNavigate();
  const [progress, setProgress] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);

  function pick() {
    setError(null);
    inputRef.current?.click();
  }

  async function onFile(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    e.target.value = ""; // allow re-picking the same file
    if (!file) return;
    setProgress(0);
    try {
      const receipt = await uploadReceipt({
        file,
        onProgress: ({ loaded, total }) => {
          setProgress(total ? Math.round((loaded / total) * 100) : null);
        },
      });
      setProgress(null);
      navigate(`/receipts/${receipt.id}/processing`);
    } catch (err) {
      setProgress(null);
      const msg =
        err instanceof ApiError
          ? `${err.message}`
          : err instanceof Error
            ? err.message
            : "Upload failed";
      setError(msg);
    }
  }

  const busy = progress !== null;

  if (fab) {
    return (
      <>
        <button
          type="button"
          aria-label={label}
          onClick={pick}
          disabled={busy}
          className={
            "fixed bottom-20 right-5 z-30 h-16 w-16 rounded-full bg-sky-600 text-white " +
            "shadow-xl shadow-sky-600/30 flex items-center justify-center " +
            "active:scale-95 transition-transform disabled:opacity-70 " +
            "[bottom:calc(5rem+env(safe-area-inset-bottom))] " +
            (className ?? "")
          }
        >
          {busy ? (
            <div className="flex flex-col items-center">
              <Loader2 className="h-6 w-6 animate-spin" />
              <span className="text-[10px] mt-0.5">{progress ?? 0}%</span>
            </div>
          ) : (
            <Camera className="h-7 w-7" />
          )}
        </button>
        <input
          ref={inputRef}
          type="file"
          accept="image/*"
          className="hidden"
          onChange={onFile}
        />
        {error && (
          <div className="fixed bottom-40 right-5 z-30 max-w-xs rounded-md bg-red-600 text-white text-xs px-3 py-2 shadow">
            {error}
          </div>
        )}
      </>
    );
  }

  return (
    <>
      <Button
        type="button"
        variant={variant}
        onClick={pick}
        disabled={busy}
        className={className}
      >
        {busy ? (
          <>
            <Loader2 className="h-4 w-4 mr-2 animate-spin" />
            Uploading {progress ?? 0}%
          </>
        ) : (
          <>
            <Camera className="h-4 w-4 mr-2" />
            {label}
          </>
        )}
      </Button>
      <input
        ref={inputRef}
        type="file"
        accept="image/*"
        capture="environment"
        className="hidden"
        onChange={onFile}
      />
      {error && (
        <p className="mt-2 text-sm text-red-600">{error}</p>
      )}
    </>
  );
}
