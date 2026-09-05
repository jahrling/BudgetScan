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
      receipt_id?: number | null;
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
      excluded?: boolean | null;
    }) => api.patch<TransactionDetail>(`/transactions/${id}`, data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["transactions"] });
      qc.invalidateQueries({ queryKey: ["budgets"] });
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

export interface CategorizedTransaction {
  transaction_id: number;
  description: string | null;
  amount_cents: number;
  current_category_name: string | null;
  category_id: number | null;
  category_name: string | null;
  confidence: number;
  source: string;
  tier: string;
  needs_review: boolean;
  merchant_guess: string | null;
}

export interface CategorizeResponse {
  results: CategorizedTransaction[];
  processed: number;
  skipped: number;
}

export function useCategorizeTransactions() {
  return useMutation({
    mutationFn: (body: {
      transaction_ids?: number[];
      limit?: number;
      skip_llm?: boolean;
    }) => api.post<CategorizeResponse>("/transactions/categorize", body),
  });
}

export function useApplyCategories() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (items: { transaction_id: number; category_id: number }[]) =>
      api.post<{ applied: number; rules_created: number }>(
        "/transactions/apply-categories",
        { items }
      ),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["transactions"] });
      qc.invalidateQueries({ queryKey: ["budgets"] });
    },
  });
}

export function useConfirmCategory() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      txnId,
      category_id,
      merchant_name,
    }: {
      txnId: number;
      category_id: number;
      merchant_name?: string | null;
    }) =>
      api.post<{ transaction_id: number; category_id: number; rule_id: number | null; merchant_updated: boolean }>(
        `/transactions/${txnId}/confirm-category`,
        { category_id, merchant_name }
      ),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["transactions"] });
    },
  });
}

export function useGenerateRules() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body?: { transaction_ids?: number[] }) =>
      api.post<{
        drafts_created: number;
        batches_processed: number;
        transactions_covered: number;
        errors: string[];
      }>("/transactions/generate-rules", body ?? {}),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["rules"] });
    },
  });
}

export function useDetectRecurring() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () =>
      api.post<{
        groups_found: number;
        transactions_flagged: number;
        transactions_cleared: number;
        by_cadence: Record<string, number>;
      }>("/transactions/detect-recurring", {}),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["transactions"] });
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
