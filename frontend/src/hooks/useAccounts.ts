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
