import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../lib/api";
import type {
  LineItem,
  LineItemInput,
  TransactionDetail,
  TransactionListResponse,
} from "../types/models";

export function useTransactions(params: Record<string, string> = {}) {
  const qs = new URLSearchParams(params).toString();
  return useQuery({
    queryKey: ["transactions", params],
    queryFn: () =>
      api.get<TransactionListResponse>(`/transactions${qs ? `?${qs}` : ""}`),
  });
}

export function useTransaction(id: number | null) {
  return useQuery({
    queryKey: ["transactions", id],
    queryFn: () => api.get<TransactionDetail>(`/transactions/${id}`),
    enabled: id !== null,
  });
}

export function useCreateTransaction() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: {
      account_id: number;
      merchant_id?: number | null;
      posted_at: string;
      amount_cents: number;
      description?: string | null;
      line_items?: LineItemInput[];
    }) => api.post<TransactionDetail>("/transactions", data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["transactions"] });
      qc.invalidateQueries({ queryKey: ["budgets"] });
    },
  });
}

export function useUpdateTransaction() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      id,
      ...data
    }: {
      id: number;
      description?: string | null;
      status?: string;
    }) => api.patch<TransactionDetail>(`/transactions/${id}`, data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["transactions"] });
    },
  });
}

export function useDeleteTransaction() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => api.delete(`/transactions/${id}`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["transactions"] });
      qc.invalidateQueries({ queryKey: ["budgets"] });
    },
  });
}

export function useReplaceLineItems() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      txnId,
      line_items,
    }: {
      txnId: number;
      line_items: LineItemInput[];
    }) => api.put<LineItem[]>(`/transactions/${txnId}/line_items`, { line_items }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["transactions"] });
      qc.invalidateQueries({ queryKey: ["budgets"] });
    },
  });
}
