/**
 * Client for the Flight Price Notifier AWS API (API Gateway HTTP API → Lambda → DynamoDB).
 * The browser holds no AWS credentials. Every call carries the Supabase access token; the
 * Lambdas read the subscriber's email from that verified session, never from the request body.
 *
 * M2 paywall: a subscription only gets alerts once ECPay confirms payment (status `active`),
 * or while a cancelled subscription is still inside its paid period.
 */
import { supabase } from "@/integrations/supabase/client";

const API_BASE = (import.meta.env.VITE_FLIGHT_API_URL ?? "").replace(/\/+$/, "");

export type PlanName = "tokyo" | "seoul" | "london";
export type SubscriptionStatus = "pending_payment" | "active" | "cancelled" | "expired";

export interface Subscription {
  email: string;
  route: string;
  plan_name: PlanName;
  origin: string;
  destination: string;
  target_price: number;
  currency: "TWD";
  subscription_status: SubscriptionStatus;
  /** Paid-through date (UTC, `YYYY-MM-DDTHH:MM:SSZ`) and its Taipei-date label. */
  current_period_end?: string;
  current_period_end_date?: string;
  amount?: number;
  created_at: string;
  updated_at: string;
}

export interface Plan {
  planName: PlanName;
  label: string;
  labelEn: string;
  route: string;
  /** Recent cheapest next-month round trip, shown only as a hint for picking a budget. */
  referencePrice: number;
}

export const PLANS: Plan[] = [
  {
    planName: "tokyo",
    label: "台北 ✈ 東京",
    labelEn: "Taipei → Tokyo",
    route: "TPE-TYO",
    referencePrice: 7200,
  },
  {
    planName: "seoul",
    label: "台北 ✈ 首爾",
    labelEn: "Taipei → Seoul",
    route: "TPE-SEL",
    referencePrice: 6400,
  },
  {
    planName: "london",
    label: "台北 ✈ 倫敦",
    labelEn: "Taipei → London",
    route: "TPE-LON",
    referencePrice: 22600,
  },
];

export const formatTwd = (n: number) => `NT$${Math.round(n).toLocaleString("en-US")}`;

async function session(): Promise<{ token: string; email: string }> {
  const { data } = await supabase.auth.getSession();
  const token = data.session?.access_token;
  if (!token) throw new Error("登入已過期，請重新登入");
  return { token, email: (data.session?.user.email ?? "").toLowerCase() };
}

async function call(path: string, init: RequestInit = {}): Promise<Response> {
  if (!API_BASE) throw new Error("VITE_FLIGHT_API_URL is not configured");
  const { token } = await session();
  const headers = { ...(init.headers as Record<string, string>), Authorization: `Bearer ${token}` };
  const res = await fetch(`${API_BASE}${path}`, { ...init, headers });
  if (!res.ok) {
    const data = (await res.json().catch(() => ({}))) as { error?: string };
    throw new Error(data.error ?? `Request failed (HTTP ${res.status})`);
  }
  return res;
}

function normalize(s: Subscription): Subscription {
  // Rows created before the paywall have no status: treat them as unpaid.
  return { ...s, subscription_status: s.subscription_status ?? "pending_payment" };
}

export interface SubscriptionList {
  subscriptions: Subscription[];
  monthlyPrice: number | null;
}

export async function listSubscriptions(): Promise<SubscriptionList> {
  // `email` is ignored by the API (it trusts the token); kept only for backward compatibility.
  const { email } = await session();
  const res = await call(`/subscriptions?email=${encodeURIComponent(email)}`);
  const data = (await res.json()) as {
    subscriptions: Subscription[];
    monthly_price?: number | null;
  };
  return {
    subscriptions: data.subscriptions.map(normalize),
    monthlyPrice: data.monthly_price ?? null,
  };
}

export type SaveResult =
  { kind: "checkout"; html: string } | { kind: "updated"; subscription: Subscription };

/**
 * POST /subscribe. The API answers either:
 * - text/html → ECPay's auto-submit checkout form (new / unpaid subscription), or
 * - application/json → an in-place target-price update for a paid (or paid-through) subscription.
 */
export async function saveSubscription(input: {
  plan_name: PlanName;
  target_price: number;
}): Promise<SaveResult> {
  const { email } = await session();
  const res = await call("/subscribe", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ ...input, email }), // email ignored by the API; the token decides
  });
  if ((res.headers.get("content-type") ?? "").includes("text/html")) {
    return { kind: "checkout", html: await res.text() };
  }
  const data = (await res.json()) as { subscription: Subscription };
  return { kind: "updated", subscription: normalize(data.subscription) };
}

/** Hand the browser to ECPay's cashier: the returned page auto-submits its form. */
export function goToCheckout(html: string) {
  document.open();
  document.write(html);
  document.close();
}

export async function cancelSubscription(route: string): Promise<Subscription | null> {
  const res = await call("/cancel", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ route }),
  });
  const data = (await res.json()) as { subscription?: Subscription };
  return data.subscription ? normalize(data.subscription) : null;
}
