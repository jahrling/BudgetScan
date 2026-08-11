import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../lib/api";
import type { Budget, BudgetStatusItem } from "../types/models";

export function useBudgets() {
  return useQuery({
    queryKey: ["budgets"],
    queryFn: () => api.get<Budget[]>("/budgets"),
  });
}

export function useBudgetStatus() {
  return useQuery({
    queryKey: ["budgets", "status"],
    queryFn: () =>
      api.get<BudgetStatusItem[]>("/budgets/status?period=current_month"),
  });
}

export interface SpendingSuggestion {
  category_id: number;
  category_name: string;
  avg_monthly_cents: number;
  suggested_cents: number;
  total_cents: number;
  months: number;
  txn_count: number;
}

export function useSpendingSuggestions(months = 3) {
  return useQuery({
    queryKey: ["budgets", "suggestions", months],
    queryFn: () =>
      api.get<SpendingSuggestion[]>(`/budgets/suggestions?months=${months}`),
  });
}

export function useCreateBudget() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: {
      category_id: number;
      period: string;
      amount_cents: number;
      start_date: string;
      end_date?: string | null;
    }) => api.post<Budget>("/budgets", data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["budgets"] });
    },
  });
}

export function useUpdateBudget() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      id,
      ...data
    }: {
      id: number;
      category_id?: number;
      period?: string;
      amount_cents?: number;
      start_date?: string;
      end_date?: string | null;
      is_pinned?: boolean;
    }) => api.patch<Budget>(`/budgets/${id}`, data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["budgets"] });
    },
  });
}

export function useDeleteBudget() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => api.delete(`/budgets/${id}`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["budgets"] });
    },
  });
}
