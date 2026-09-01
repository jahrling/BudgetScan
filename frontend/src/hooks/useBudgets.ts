import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../lib/api";
import type {
  Budget,
  BudgetStatusItem,
  IncomeSummary,
  MonthComparison,
  UnbudgetedSpend,
} from "../types/models";

export function useBudgets(month: string) {
  return useQuery({
    queryKey: ["budgets", month],
    queryFn: () => api.get<Budget[]>(`/budgets?month=${month}`),
  });
}

export function useBudgetStatus(month: string) {
  return useQuery({
    queryKey: ["budgets", "status", month],
    queryFn: () => api.get<BudgetStatusItem[]>(`/budgets/status?month=${month}`),
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
  is_income: boolean;
}

export function useSpendingSuggestions(months = 3) {
  return useQuery({
    queryKey: ["budgets", "suggestions", months],
    queryFn: () =>
      api.get<SpendingSuggestion[]>(`/budgets/suggestions?months=${months}`),
  });
}

export function useIncomeSummary(month: string) {
  return useQuery({
    queryKey: ["budgets", "income-summary", month],
    queryFn: () =>
      api.get<IncomeSummary>(`/budgets/income-summary?month=${month}`),
  });
}

export function useUnbudgetedSpend(month: string) {
  return useQuery({
    queryKey: ["budgets", "unbudgeted-spend", month],
    queryFn: () =>
      api.get<UnbudgetedSpend>(`/budgets/unbudgeted-spend?month=${month}`),
  });
}

export function useMonthComparison(month: string) {
  return useQuery({
    queryKey: ["budgets", "comparison", month],
    queryFn: () =>
      api.get<MonthComparison>(`/budgets/comparison?month=${month}`),
  });
}

export function useCreateBudget() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: {
      category_id: number;
      year_month: string;
      amount_cents: number;
      period?: string;
      start_date?: string;
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
      year_month?: string;
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

export function useSeedMonth() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (month: string) =>
      api.post<Budget[]>(`/budgets/seed?month=${month}`, {}),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["budgets"] });
    },
  });
}
