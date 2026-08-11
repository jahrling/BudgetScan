import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { useNavigate, useLocation } from "react-router-dom";
import { Upload } from "lucide-react";
import { uploadReceipt } from "../hooks/useReceipts";

const IMPORT_EXTENSIONS = new Set([".qfx", ".ofx", ".qif"]);
const IMAGE_EXTENSIONS = new Set([".jpg", ".jpeg", ".png", ".heic", ".webp", ".gif", ".bmp", ".tiff"]);

function fileExtension(name: string): string {
  const dot = name.lastIndexOf(".");
  return dot >= 0 ? name.slice(dot).toLowerCase() : "";
}

type FileRoute = "import" | "receipt" | null;

function routeForFile(file: File): FileRoute {
  const ext = fileExtension(file.name);
  if (IMPORT_EXTENSIONS.has(ext)) return "import";
  if (IMAGE_EXTENSIONS.has(ext) || file.type.startsWith("image/")) return "receipt";
  return null;
}

interface DropContextValue {
  pendingFile: File | null;
  consumeFile: () => File | null;
  resetDrag: () => void;
}

const DropContext = createContext<DropContextValue>({
  pendingFile: null,
  consumeFile: () => null,
  resetDrag: () => {},
});

export function usePendingFile() {
  return useContext(DropContext);
}

export function GlobalDropZone({ children }: { children: ReactNode }) {
  const [dragging, setDragging] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [pendingFile, setPendingFile] = useState<File | null>(null);
  const dragCounter = useRef(0);
  const navigate = useNavigate();
  const location = useLocation();

  const consumeFile = useCallback(() => {
    const f = pendingFile;
    setPendingFile(null);
    return f;
  }, [pendingFile]);

  const resetDrag = useCallback(() => {
    dragCounter.current = 0;
    setDragging(false);
  }, []);

  useEffect(() => {
    if (uploadError) {
      const t = setTimeout(() => setUploadError(null), 5000);
      return () => clearTimeout(t);
    }
  }, [uploadError]);

  useEffect(() => {
    function onDragEnter(e: DragEvent) {
      e.preventDefault();
      dragCounter.current++;
      if (dragCounter.current === 1) setDragging(true);
    }

    function onDragLeave(e: DragEvent) {
      e.preventDefault();
      dragCounter.current--;
      if (dragCounter.current <= 0) {
        dragCounter.current = 0;
        setDragging(false);
      }
    }

    function onDragOver(e: DragEvent) {
      e.preventDefault();
      if (e.dataTransfer) e.dataTransfer.dropEffect = "copy";
    }

    async function onDrop(e: DragEvent) {
      e.preventDefault();
      dragCounter.current = 0;
      setDragging(false);
      setUploadError(null);
      const file = e.dataTransfer?.files[0];
      if (!file) return;

      const route = routeForFile(file);
      if (!route) {
        setUploadError(`Unsupported file type: ${fileExtension(file.name) || file.type || "unknown"}`);
        return;
      }

      if (route === "import") {
        setPendingFile(file);
        if (location.pathname !== "/sync") navigate("/sync");
      } else if (route === "receipt") {
        setUploading(true);
        try {
          const receipt = await uploadReceipt({ file });
          navigate(`/receipts/${receipt.id}/processing`);
        } catch (err) {
          setUploadError(err instanceof Error ? err.message : "Receipt upload failed");
        } finally {
          setUploading(false);
        }
      }
    }

    document.addEventListener("dragenter", onDragEnter);
    document.addEventListener("dragleave", onDragLeave);
    document.addEventListener("dragover", onDragOver);
    document.addEventListener("drop", onDrop);
    return () => {
      document.removeEventListener("dragenter", onDragEnter);
      document.removeEventListener("dragleave", onDragLeave);
      document.removeEventListener("dragover", onDragOver);
      document.removeEventListener("drop", onDrop);
    };
  }, [location.pathname, navigate]);

  return (
    <DropContext.Provider value={{ pendingFile, consumeFile, resetDrag }}>
      {children}
      {(dragging || uploading) && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm pointer-events-none">
          <div className="flex flex-col items-center rounded-2xl border-2 border-dashed border-white/70 bg-white/10 px-12 py-10">
            <Upload className="h-12 w-12 text-white mb-3" />
            <p className="text-lg font-semibold text-white">
              {uploading ? "Uploading…" : "Drop file to upload"}
            </p>
            <p className="text-sm text-white/70 mt-1">
              QFX, QIF, or receipt image
            </p>
          </div>
        </div>
      )}
      {uploadError && (
        <div className="fixed bottom-6 left-1/2 -translate-x-1/2 z-50 rounded-lg bg-red-600 text-white text-sm px-4 py-2.5 shadow-lg">
          {uploadError}
        </div>
      )}
    </DropContext.Provider>
  );
}
