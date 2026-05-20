export interface Category {
  id: number;
  name: string;
  parent_id: number | null;
  color: string | null;
  icon: string | null;
  created_at: string;
  updated_at: string;
}

export interface Budget {
  id: number;
  category_id: number;
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
  merchant_name: string | null;
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
