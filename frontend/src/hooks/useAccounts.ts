import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../lib/api";
import type { Account } from "../types/models";

export function useAccounts() {
  return useQuery({
    queryKey: ["accounts"],
    queryFn: () => api.get<Account[]>("/accounts"),
  });
}

export function useCreateAccount() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: { name: string; type: string; quicken_id?: string | null }) =>
      api.post<Account>("/accounts", data),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["accounts"] }),
  });
}

export function useUpdateAccount() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      id,
      ...data
    }: {
      id: number;
      name?: string;
      type?: string;
    }) => api.patch<Account>(`/accounts/${id}`, data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["accounts"] });
      qc.invalidateQueries({ queryKey: ["investments"] });
    },
  });
}

export function useMergeAccounts() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: { source_id: number; target_id: number }) =>
      api.post<{
        target_id: number;
        source_deleted: boolean;
        rows_reassigned: Record<string, number>;
      }>("/accounts/merge", data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["accounts"] });
      qc.invalidateQueries({ queryKey: ["investments"] });
      qc.invalidateQueries({ queryKey: ["transactions"] });
    },
  });
}
