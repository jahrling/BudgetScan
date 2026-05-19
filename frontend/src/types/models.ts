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
  created_at: string;
  updated_at: string;
}

export interface BudgetStatusItem {
  category_id: number;
  category_name: string;
  budgeted_cents: number;
  spent_cents: number;
  remaining_cents: number;
  percent_used: number;
}
