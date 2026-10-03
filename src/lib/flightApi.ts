/**
 * Client for the Flight Price Notifier AWS API (API Gateway HTTP API → Lambda → DynamoDB).
 * The browser holds no AWS credentials; it only calls these two public routes.
 * M1 has no payment guard: a subscription row means "eligible for alerts".
 */

const API_BASE = (import.meta.env.VITE_FLIGHT_API_URL ?? "").replace(/\/+$/, "");

export type PlanName = "tokyo" | "seoul";

export interface Subscription {
  email: string;
  route: string;
  plan_name: PlanName;
  origin: string;
  destination: string;
  target_price: number;
  currency: "TWD";
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
];

export const formatTwd = (n: number) => `NT$${Math.round(n).toLocaleString("en-US")}`;

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  if (!API_BASE) throw new Error("VITE_FLIGHT_API_URL is not configured");
  const res = await fetch(`${API_BASE}${path}`, init);
  const data = (await res.json().catch(() => ({}))) as { error?: string };
  if (!res.ok) throw new Error(data.error ?? `Request failed (HTTP ${res.status})`);
  return data as T;
}

export async function listSubscriptions(email: string): Promise<Subscription[]> {
  const data = await request<{ subscriptions: Subscription[] }>(
    `/subscriptions?email=${encodeURIComponent(email)}`,
  );
  return data.subscriptions;
}

export async function saveSubscription(input: {
  email: string;
  plan_name: PlanName;
  target_price: number;
}): Promise<Subscription> {
  const data = await request<{ subscription: Subscription }>("/subscribe", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(input),
  });
  return data.subscription;
}
