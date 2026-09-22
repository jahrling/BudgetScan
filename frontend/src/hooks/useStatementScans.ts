import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, apiFetch, ApiError } from "../lib/api";
import type {
  MaterializeRequest,
  PositionSnapshot,
  StatementReviewPreview,
  StatementScan,
} from "../types/models";

export function useStatementScan(id: number | null) {
  return useQuery({
    queryKey: ["statement-scans", id],
    queryFn: () => api.get<StatementScan>(`/statement-scans/${id}`),
    enabled: id !== null,
    refetchInterval: (q) => {
      const s = q.state.data as StatementScan | undefined;
      if (!s) return 2000;
      if (s.ocr_status === "pending") return 2000;
      return false;
    },
  });
}

export function uploadStatementScan(file: File): Promise<StatementScan> {
  return new Promise((resolve, reject) => {
    const form = new FormData();
    form.append("file", file);
    const xhr = new XMLHttpRequest();
    xhr.open("POST", "/api/statement-scans");
    xhr.withCredentials = true;
    xhr.responseType = "json";
    xhr.addEventListener("load", () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        resolve(xhr.response as StatementScan);
      } else {
        const detail = xhr.response?.detail ?? `HTTP ${xhr.status}`;
        reject(new ApiError(xhr.status, detail));
      }
    });
    xhr.addEventListener("error", () => reject(new ApiError(0, "Network error")));
    xhr.send(form);
  });
}

export function useReprocessScan() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) =>
      apiFetch<StatementScan>(`/api/statement-scans/${id}/reprocess?force=true`, {
        method: "POST",
      }),
    onSuccess: (_data, id) => {
      qc.invalidateQueries({ queryKey: ["statement-scans", id] });
    },
  });
}

export function useStatementPreview(scanId: number | null) {
  return useQuery({
    queryKey: ["statement-preview", scanId],
    queryFn: () =>
      api.get<StatementReviewPreview>(`/statement-scans/${scanId}/preview`),
    enabled: scanId !== null,
    staleTime: Infinity,
  });
}

export function useMaterializeStatement() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      scanId,
      ...body
    }: MaterializeRequest & { scanId: number }) =>
      api.post<PositionSnapshot[]>(
        `/statement-scans/${scanId}/materialize`,
        body,
      ),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["investments"] });
      qc.invalidateQueries({ queryKey: ["snapshots"] });
    },
  });
}

export function statementImageUrl(scanId: number): string {
  return `/api/statement-scans/${scanId}/image`;
}
