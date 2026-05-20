import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, apiFetch, ApiError } from "../lib/api";
import type { Receipt, TransactionDetail } from "../types/models";

export function useReceipt(id: number | null, refetchIntervalMs?: number | false) {
  return useQuery({
    queryKey: ["receipts", id],
    queryFn: () => api.get<Receipt>(`/receipts/${id}`),
    enabled: id !== null,
    refetchInterval: (q) => {
      const r = q.state.data as Receipt | undefined;
      if (!r) return refetchIntervalMs ?? 2000;
      if (r.ocr_status === "pending") return refetchIntervalMs ?? 2000;
      return false;
    },
  });
}

interface UploadProgress {
  loaded: number;
  total: number;
}

interface UploadOptions {
  file: File;
  onProgress?: (p: UploadProgress) => void;
}

/**
 * Uploads via XHR rather than fetch so we can stream progress events to the
 * caller (fetch's body upload is not observable in browsers).
 */
export function uploadReceipt({ file, onProgress }: UploadOptions): Promise<Receipt> {
  return new Promise((resolve, reject) => {
    const form = new FormData();
    form.append("file", file);
    const xhr = new XMLHttpRequest();
    xhr.open("POST", "/api/receipts");
    xhr.withCredentials = true;
    xhr.responseType = "json";
    xhr.upload.addEventListener("progress", (e) => {
      if (e.lengthComputable && onProgress) {
        onProgress({ loaded: e.loaded, total: e.total });
      }
    });
    xhr.addEventListener("load", () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        resolve(xhr.response as Receipt);
      } else {
        const detail = xhr.response?.detail ?? `HTTP ${xhr.status}`;
        reject(new ApiError(xhr.status, detail));
      }
    });
    xhr.addEventListener("error", () => reject(new ApiError(0, "Network error")));
    xhr.send(form);
  });
}

export function useUploadReceipt() {
  return useMutation({
    mutationFn: (opts: UploadOptions) => uploadReceipt(opts),
  });
}

export function useReprocessReceipt() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) =>
      apiFetch<Receipt>(`/api/receipts/${id}/process?force=true`, { method: "POST" }),
    onSuccess: (_data, id) => {
      qc.invalidateQueries({ queryKey: ["receipts", id] });
    },
  });
}

export function useReceiptToTransaction() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      receiptId,
      account_id,
      merchant_id,
    }: {
      receiptId: number;
      account_id: number;
      merchant_id?: number | null;
    }) =>
      api.post<TransactionDetail>(`/receipts/${receiptId}/to-transaction`, {
        account_id,
        merchant_id: merchant_id ?? null,
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["transactions"] });
      qc.invalidateQueries({ queryKey: ["budgets"] });
    },
  });
}

export function receiptImageUrl(receiptId: number): string {
  return `/api/receipts/${receiptId}/image`;
}
