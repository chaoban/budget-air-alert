/**
 * Public pricing shown on the landing page (no login needed, so it can't come from the API).
 * Must match `amount` in the `flight/ecpay` secret, which is what ECPay actually charges.
 * Change both together.
 */
export const MONTHLY_PRICE_TWD = 300;

/** Site contact details (shown in the footer on every page). */
export const CONTACT = {
  company: "SAISAI",
  phone: "0912-581-963",
  phoneHref: "tel:+886912581963",
  email: "mm579016@ms17.hinet.net",
} as const;
