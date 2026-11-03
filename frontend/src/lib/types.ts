export type RiskCategory = "low" | "medium" | "high" | "critical";
export type Role = "admin" | "analyst" | "viewer";

export interface User { user_id: string; email: string; full_name: string; role: Role; tenant_id: string }

export interface Transaction {
  transaction_id: string; seq: number; event_timestamp: string; ingested_at: string; customer_id: string;
  merchant_id: string; merchant_name: string; merchant_category: string; amount: string; currency: string;
  country: string; device_id: string; payment_channel: string; status: string; is_late: boolean;
  risk_score: number | null; risk_category: RiskCategory | null; probability: number | null;
  scored_at: string | null; model_version: string | null; alert_id: number | null; alert_status: string | null;
}

export interface Explanation { feature: string; value: number | null; baseline: number; contribution: number; description: string }

export interface TransactionDetail extends Transaction {
  features: Record<string, number | null>; explanation: Explanation[]; explanation_text: string[];
  scoring_latency_ms: number; decision_threshold: number; kafka_partition: number; kafka_offset: number; payload_hash: string;
}

export interface Alert {
  alert_id: number; status: string; severity: string; created_at: string; transaction_id: string;
  event_timestamp: string; customer_id: string; merchant_id: string; merchant_name: string; merchant_category: string;
  amount: string; currency: string; country: string; payment_channel: string; risk_score: number;
  risk_category: RiskCategory; top_reasons: string[]; investigation_id: string | null; investigation_priority: string | null;
}

export interface Evidence { id: string; tool: string; title: string; summary: string; record_ids: string[]; data: Record<string, unknown> }
export interface Indicator { code: string; description: string; weight: number; evidence: string[] }

export interface Investigation {
  investigation_id: string; tenant_id: string; transaction_id: string; alert_id: number | null; engine: "deterministic" | "ollama";
  llm_model: string | null; priority: "P1" | "P2" | "P3" | "P4"; review_status: string; reviewer_notes: string | null;
  duration_ms: number; created_at: string; updated_at: string; created_by_name: string;
  report: {
    transaction_summary: string; risk_score: number | null; risk_category: RiskCategory | null; model_version: string | null;
    suspicious_indicators: Indicator[]; evidence: Evidence[]; timeline: { at: string; event: string; ref: string; evidence: string }[];
    narrative: string; recommended_priority: string; recommended_action: string; engine: string; llm_model: string | null;
    llm_note: string | null; limitations: string[];
  };
}

export interface InvestigationRow {
  investigation_id: string; transaction_id: string; engine: string; priority: string; review_status: string;
  created_at: string; risk_score: number | null; indicator_count: number; created_by_name: string; duration_ms: number;
}
