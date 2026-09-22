import { useQuery } from "@tanstack/react-query";
import { api } from "../lib/api";
import type {
  HoldingDetailResponse,
  HoldingSummary,
  InvestmentOverview,
  InvestmentSettings,
  PerformanceData,
  Security,
} from "../types/models";

export function useInvestmentOverview() {
  return useQuery({
    queryKey: ["investments", "overview"],
    queryFn: () => api.get<InvestmentOverview>("/investments/overview"),
  });
}

export function useHoldings(accountId?: number) {
  return useQuery({
    queryKey: ["investments", "holdings", { accountId }],
    queryFn: () => {
      const params = accountId != null ? `?account_id=${accountId}` : "";
      return api.get<HoldingSummary[]>(`/investments/holdings${params}`);
    },
  });
}

export function useHoldingDetail(securityId: number | null, accountId?: number) {
  return useQuery({
    queryKey: ["investments", "holdings", securityId, { accountId }],
    queryFn: () => {
      const params = accountId != null ? `?account_id=${accountId}` : "";
      return api.get<HoldingDetailResponse>(`/investments/holdings/${securityId}${params}`);
    },
    enabled: securityId != null,
  });
}

export function useSecurities() {
  return useQuery({
    queryKey: ["investments", "securities"],
    queryFn: () => api.get<Security[]>("/investments/securities"),
  });
}

export function usePerformance(accountId?: number) {
  return useQuery({
    queryKey: ["investments", "performance", { accountId }],
    queryFn: () => {
      const params = accountId != null ? `?account_id=${accountId}` : "";
      return api.get<PerformanceData>(`/investments/performance${params}`);
    },
  });
}

export function useInvestmentSettings() {
  return useQuery({
    queryKey: ["investments", "settings"],
    queryFn: () => api.get<InvestmentSettings>("/investments/settings"),
  });
}
