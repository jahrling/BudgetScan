import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../lib/api";

export interface TransferPair {
  pair_id: number;
  debit_txn_id: number;
  credit_txn_id: number;
  debit_account_id: number;
  credit_account_id: number;
  debit_account_name: string | null;
  credit_account_name: string | null;
  amount_cents: number;
  debit_description: string | null;
  credit_description: string | null;
  debit_posted_at: string;
  credit_posted_at: string;
}

interface TransferListResponse {
  items: TransferPair[];
  total: number;
}

interface DetectResponse {
  new_pairs: number;
  cleared_pairs: number;
  total_pairs: number;
}

export function useTransferPairs(offset = 0, limit = 50) {
  return useQuery({
    queryKey: ["transfers", offset, limit],
    queryFn: () =>
      api.get<TransferListResponse>(
        `/transfers?offset=${offset}&limit=${limit}`,
      ),
  });
}

export function useDetectTransfers() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: {
      account_ids?: number[];
      window_days?: number;
      dry_run?: boolean;
    }) => api.post<DetectResponse>("/transfers/detect", data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["transfers"] });
      qc.invalidateQueries({ queryKey: ["transactions"] });
    },
  });
}

export function useRemoveTransferPair() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (pairId: number) => api.delete(`/transfers/${pairId}`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["transfers"] });
      qc.invalidateQueries({ queryKey: ["transactions"] });
    },
  });
}
