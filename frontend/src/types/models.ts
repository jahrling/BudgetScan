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
