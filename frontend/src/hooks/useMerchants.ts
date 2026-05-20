import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../lib/api";
import type { Merchant } from "../types/models";

export function useMerchants() {
  return useQuery({
    queryKey: ["merchants"],
    queryFn: () => api.get<Merchant[]>("/merchants"),
  });
}

export function useSearchMerchants(q: string) {
  return useQuery({
    queryKey: ["merchants", "search", q],
    queryFn: () => api.get<Merchant[]>(`/merchants/search?q=${encodeURIComponent(q)}`),
    enabled: q.length >= 1,
  });
}

export function useCreateMerchant() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: { name: string }) =>
      api.post<Merchant>("/merchants", data),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["merchants"] }),
  });
}
