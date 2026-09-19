export interface Category {
  id: number;
  name: string;
  parent_id: number | null;
  color: string | null;
  icon: string | null;
  is_income: boolean;
  source: string;
  created_at: string;
  updated_at: string;
}

export interface Budget {
  id: number;
  category_id: number;
  year_month: string;
  period: string;
  amount_cents: number;
  start_date: string;
  end_date: string | null;
  is_pinned: boolean;
  created_at: string;
  updated_at: string;
}

export interface BudgetStatusItem {
  budget_id: number;
  category_id: number;
  category_name: string;
  category_icon: string | null;
  category_color: string | null;
  budgeted_cents: number;
  spent_cents: number;
  remaining_cents: number;
  percent_used: number;
  percent_remaining: number;
  is_pinned: boolean;
  period: string;
  period_start: string;
  period_end: string;
  days_remaining: number;
}

export interface IncomeCategoryItem {
  category_id: number;
  category_name: string;
  category_icon: string | null;
  category_color: string | null;
  amount_cents: number;
  txn_count: number;
}

export interface IncomeSummary {
  total_cents: number;
  categories: IncomeCategoryItem[];
}

export interface UnbudgetedSpendItem {
  category_id: number | null;
  category_name: string;
  spent_cents: number;
  txn_count: number;
}

export interface UnbudgetedSpend {
  total_cents: number;
  items: UnbudgetedSpendItem[];
}

export interface MonthComparisonItem {
  category_id: number;
  category_name: string;
  category_icon: string | null;
  category_color: string | null;
  current_budgeted_cents: number;
  current_spent_cents: number;
  prior_spent_cents: number;
  prior_budgeted_cents: number;
}

export interface MonthComparison {
  current_month: string;
  prior_month: string;
  items: MonthComparisonItem[];
}

export interface Rule {
  id: number;
  payee: string;
  normalized_payee: string;
  category_path: string;
  category_id: number | null;
  amount_cents: number | null;
  transfer_account: string | null;
  kind: string;
  source: string;
  status: string;
  created_at: string;
  updated_at: string;
}

export interface RuleListResponse {
  rules: Rule[];
  total: number;
}

export interface DraftGenerationResponse {
  drafts_created: number;
  skipped_existing: number;
  conflicts: { payee: string; category_ids: number[]; transaction_count: number }[];
}

export interface Account {
  id: number;
  name: string;
  type: string;
  quicken_id: string | null;
  currency: string;
  created_at: string;
  updated_at: string;
}

export interface Merchant {
  id: number;
  name: string;
  normalized_name: string;
  default_category_id: number | null;
  default_category_name: string | null;
  notes: string | null;
  created_at: string;
  updated_at: string;
}

export interface LineItem {
  id: number;
  transaction_id: number;
  category_id: number;
  category_name: string | null;
  description: string | null;
  quantity: number | null;
  unit_price_cents: number | null;
  amount_cents: number;
  ocr_confidence: number | null;
  user_modified: boolean;
  created_at: string;
  updated_at: string;
}

export interface Transaction {
  id: number;
  account_id: number;
  merchant_id: number | null;
  posted_at: string;
  amount_cents: number;
  description: string | null;
  quicken_id: string | null;
  receipt_id: number | null;
  status: string;
  transfer_pair_id: number | null;
  category_id: number | null;
  category_source: string | null;
  category_confidence: number | null;
  needs_review: boolean;
  excluded: boolean | null;
  is_recurring: boolean | null;
  recurrence_cadence: string | null;
  recurrence_group_id: number | null;
  merchant_name: string | null;
  account_name: string | null;
  category_name: string | null;
  transfer_account_name: string | null;
  created_at: string;
  updated_at: string;
}

export interface TransactionDetail extends Transaction {
  line_items: LineItem[];
}

export interface TransactionListResponse {
  items: Transaction[];
  total: number;
}

export interface LineItemInput {
  category_id: number;
  description?: string | null;
  amount_cents: number;
}

export interface Receipt {
  id: number;
  file_path: string;
  original_filename: string;
  sha256: string;
  captured_at: string;
  ocr_raw_json: string | null;
  ocr_model: string | null;
  ocr_status: "pending" | "done" | "failed";
  ocr_error: string | null;
  created_at: string;
  updated_at: string;
}

export interface OcrPreviewItem {
  description: string | null;
  quantity: number | null;
  unit_price_cents: number | null;
  amount_cents: number;
  suggested_category_id: number;
  suggested_category_name: string | null;
}

export interface OcrPreviewResponse {
  merchant: string | null;
  date: string | null;
  total_cents: number;
  subtotal_cents: number | null;
  tax_cents: number | null;
  items: OcrPreviewItem[];
  drift_cents: number;
}

export interface ReviewLineItem {
  description: string | null;
  quantity: number | null;
  unit_price_cents: number | null;
  amount_cents: number;
  category_id: number;
  user_modified: boolean;
}

export interface ReviewTransactionRequest {
  account_id: number;
  merchant_name: string | null;
  merchant_id: number | null;
  posted_at: string;
  total_cents: number;
  items: ReviewLineItem[];
}

// ── Investment domain ─────────────────────────────────────────────────────

export interface Security {
  id: number;
  name: string;
  symbol: string | null;
  cusip: string | null;
  security_type: string;
  is_cash_equivalent: boolean;
  benchmark_security_id: number | null;
  created_at: string;
  updated_at: string;
}

export interface InvestmentTransaction {
  id: number;
  account_id: number;
  security_id: number | null;
  action: string;
  trade_date: string;
  settle_date: string | null;
  quantity_micros: number | null;
  price_micros: number | null;
  amount_cents: number;
  fee_cents: number;
  source: string;
  external_id: string | null;
  linked_transaction_id: number | null;
  memo: string | null;
  created_at: string;
  updated_at: string;
}

export interface LotDisposal {
  id: number;
  lot_id: number;
  sell_txn_id: number;
  quantity_micros: number;
  proceeds_cents: number;
  basis_cents: number;
  realized_gain_cents: number;
  term: string;
}

export interface LotDetail {
  id: number;
  account_id: number;
  security_id: number;
  opened_at: string;
  opened_by_txn_id: number | null;
  quantity_micros_original: number;
  quantity_micros_remaining: number;
  cost_basis_cents: number;
  is_reinvestment: boolean;
  source: string;
  disposals: LotDisposal[];
  created_at: string;
  updated_at: string;
}

export interface HoldingSummary {
  security_id: number;
  security_name: string;
  symbol: string | null;
  security_type: string;
  account_id: number;
  account_name: string;
  account_type: string;
  quantity_micros: number;
  latest_price_micros: number | null;
  latest_price_date: string | null;
  market_value_cents: number | null;
  cost_basis_cents: number;
  invested_capital_cents: number;
  unrealized_gain_cents: number | null;
  income_cents: number;
  realized_gain_cents: number;
}

export interface AccountSummary {
  id: number;
  name: string;
  type: string;
  value_cents: number | null;
  invested_capital_cents: number;
  cost_basis_cents: number;
  gain_cents: number | null;
  income_cents: number;
  holdings_count: number;
}

export interface InvestmentOverview {
  total_value_cents: number | null;
  invested_capital_cents: number;
  cost_basis_cents: number;
  total_gain_cents: number | null;
  income_cents: number;
  realized_gain_cents: number;
  accounts: AccountSummary[];
  holdings_count: number;
}

export interface HoldingDetailResponse {
  security: Security;
  account_id: number | null;
  account_name: string | null;
  quantity_micros: number;
  latest_price_micros: number | null;
  latest_price_date: string | null;
  market_value_cents: number | null;
  cost_basis_cents: number;
  invested_capital_cents: number;
  unrealized_gain_cents: number | null;
  income_cents: number;
  realized_gain_cents: number;
  lots: LotDetail[];
  transactions: InvestmentTransaction[];
}

export interface InvestmentSettings {
  id: number;
  benchmark_security_id: number | null;
  risk_free_annual_bps: number;
  default_lot_method: string;
  price_fetch_enabled: boolean;
}

export interface PositionSnapshot {
  id: number;
  account_id: number;
  security_id: number;
  as_of: string;
  quantity_micros: number;
  market_value_cents: number;
  price_micros: number | null;
  cost_basis_cents: number | null;
  source: string;
  created_at: string;
  updated_at: string;
}

// ── Statement scan domain ────────────────────────────────────────────────

export interface StatementScan {
  id: number;
  file_path: string;
  original_filename: string;
  sha256: string;
  account_id: number | null;
  as_of: string | null;
  ocr_status: "pending" | "done" | "failed";
  ocr_error: string | null;
  created_at: string;
  updated_at: string;
}

export interface StatementReviewPosition {
  symbol: string | null;
  name: string;
  quantity_micros: number;
  price_micros: number | null;
  market_value_cents: number;
  cost_basis_cents: number | null;
  matched_security_id: number | null;
  matched_security_name: string | null;
}

export interface StatementReviewPreview {
  account_name: string | null;
  statement_date: string | null;
  positions: StatementReviewPosition[];
}

export interface MaterializePosition {
  security_id: number | null;
  symbol: string | null;
  name: string;
  quantity_micros: number;
  market_value_cents: number;
  price_micros: number | null;
  cost_basis_cents: number | null;
}

export interface MaterializeRequest {
  account_id: number;
  as_of: string;
  positions: MaterializePosition[];
}
