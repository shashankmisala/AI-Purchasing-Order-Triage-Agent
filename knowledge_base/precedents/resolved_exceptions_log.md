---
doc_type: precedent
title: Resolved Exceptions Log
---

# Resolved Exceptions Log

Past PO exception resolutions, kept for consistency in future triage decisions. Each entry
records what happened, why, and the outcome.

## Case 2026-0142 — James Group (V-0017) — Duplicate PO
James Group submitted two invoices for the same $42,300 order four days apart. Investigation
confirmed their AR system had re-sent the invoice after a payment-status sync failure on
their end — not a fraud attempt. Resolution: rejected the duplicate invoice, notified James
Group, vendor reconciled and resubmitted correctly within 2 business days. No payment issue
occurred. Recommendation for future James Group duplicates: same handling — reject, notify,
do not escalate to Finance Director, this is a known recurring vendor-side system quirk.

## Case 2026-0098 — Smith-Bell (V-0164) — Price Variance
Invoice was $8,400 higher than the PO amount with no contract basis (Smith-Bell is a
fixed-price vendor with no escalation clause). Escalated to Procurement Manager, vendor
confirmed a billing-system error on their end, corrected invoice issued within 3 business
days. Recommendation: continue escalating Smith-Bell price variances as genuine exceptions;
do not assume index/escalation coverage for this vendor.

## Case 2026-0071 — Ferrell, Jones and Lewis (V-0087) — flagged as possible Duplicate PO
Two invoices for similar amounts within 2 days were initially flagged as a duplicate.
Investigation found they were two separate partial shipments of the same large order
(consistent with this vendor's documented split-shipment billing practice). Resolution:
approved both invoices after confirming distinct shipment tracking numbers. Recommendation:
always check tracking/shipment references for this vendor before rejecting as duplicate.

## Case 2025-0884 — Generic — Missing GL Code, new vendor
A newly onboarded vendor (within first 60 days) submitted an invoice with a blank GL Code.
Per the New Vendor Grace Period policy, this was routed to Vendor Clarification rather than
escalated. Vendor corrected and resubmitted within the SLA window. Recommendation: this is
the standard path for any vendor still inside their 90-day onboarding grace period.

## Case 2025-0793 — Generic — Quantity shortfall within contractual tolerance
A vendor with a documented 2% quantity-tolerance clause delivered 1.3% under the ordered
quantity. Initially flagged as a Quantity Mismatch by the rule engine; on review, the
shortfall was within the contracted tolerance band and the exception was closed with no
vendor action required. Recommendation: always check for a tolerance clause before
escalating a small quantity shortfall as a true exception.
