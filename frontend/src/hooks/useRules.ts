import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../lib/api";
import type { Rule, RuleListResponse, DraftGenerationResponse } from "../types/models";

interface RuleListParams {
  status?: string;
  search?: string;
  source?: string;
}

export function useRules(params?: RuleListParams) {
  const qs = new URLSearchParams();
  if (params?.status) qs.set("status", params.status);
  if (params?.search) qs.set("search", params.search);
  if (params?.source) qs.set("source", params.source);
  const suffix = qs.toString() ? `?${qs}` : "";

  return useQuery({
    queryKey: ["rules", params],
    queryFn: () => api.get<RuleListResponse>(`/rules${suffix}`),
  });
}

export function useGenerateDrafts() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.post<DraftGenerationResponse>("/rules/generate-drafts", {}),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["rules"] }),
  });
}

export function useBulkActivateRules() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (ruleIds: number[]) =>
      api.post<{ updated: number }>("/rules/bulk-activate", { rule_ids: ruleIds }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["rules"] }),
  });
}

export function useBulkDeleteRules() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (ruleIds: number[]) =>
      api.post<{ updated: number }>("/rules/bulk-delete", { rule_ids: ruleIds }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["rules"] }),
  });
}

export function useUpdateRule() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, ...data }: { id: number; status?: string; payee?: string; category_path?: string; category_id?: number | null }) =>
      api.patch<Rule>(`/rules/${id}`, data),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["rules"] }),
  });
}

export function useSeedRules() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.post<{ created: number; updated: number; skipped: number; missing_categories: string[] | null }>("/rules/seed", {}),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["rules"] }),
  });
}

export function useRunMonthly() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () =>
      api.post<{
        seed: { created: number; updated: number; skipped: number; missing_categories: string[] | null };
        drafts: DraftGenerationResponse;
        recurring: { groups_found: number; transactions_flagged: number; transactions_cleared: number; by_cadence: Record<string, number> };
        reindex: { indexed: number };
      }>("/rules/run-monthly", {}),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["rules"] });
      qc.invalidateQueries({ queryKey: ["transactions"] });
    },
  });
}
