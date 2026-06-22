---
doc_type: policy
title: Accounts Payable & Procurement Exception Policy Manual
version: "2.3"
effective_date: 2026-01-01
---

# Accounts Payable & Procurement Exception Policy Manual

This manual governs how PO/invoice exceptions are triaged, escalated, and resolved. It
applies to all exceptions regardless of which vendor is involved unless a vendor-specific
contract addendum states otherwise.

## Approval Authority Thresholds
- Exceptions with financial exposure under **$10,000**: AP analyst may approve directly if
  confidence is high and no contract conflict is found.
- Exceptions between **$10,000 and $250,000**: require Procurement Manager sign-off
  (Escalate to Manager).
- Exceptions **over $250,000**: require both Procurement Manager and Finance Director
  sign-off regardless of exception type or confidence.

## Duplicate Invoice Handling SOP
1. Confirm same vendor, same amount, and PO/invoice dates within the configured duplicate
   window (5 days) before treating a pair as a duplicate.
2. Check vendor-specific notes for known legitimate multi-invoice billing practices (e.g.,
   split shipments) before rejecting.
3. If confirmed duplicate: reject the later-dated invoice, notify the vendor with the
   original PO/invoice reference, and do NOT pay until the vendor confirms reconciliation.
4. Never approve a duplicate-flagged pair "to be safe" — rejecting and re-requesting is
   always the lower-risk action than risking a double payment.

## Missing Fields Handling
1. Check whether the vendor has an EDI integration note or new-vendor grace period on file
   before escalating a missing field as a compliance issue.
2. Vendor ID and GL Code may default from the PO record if the invoice-side field is blank
   and the PO-side field is present — this is not a true Missing Fields exception.
3. A blank field on BOTH PO and invoice sides is always a genuine Missing Fields exception
   requiring vendor or internal-team clarification before processing.

## New Vendor Grace Period
Vendors onboarded within the last 90 days receive a grace period: missing-field exceptions
during this window are routed to Vendor Clarification rather than treated as a compliance
escalation, to allow the vendor's team time to align with our data requirements.

## Price Variance & Quantity Mismatch — General Rule
Before escalating, check the vendor's contract for: price-escalation/index clauses, volume
discount schedules, annual adjustment clauses, and quantity-tolerance clauses. A variance
that falls within a documented, contractually-authorized band is not a true exception. A
variance outside any such band — or for a vendor with a strict fixed-price/no-tolerance
contract — is a genuine exception and should proceed through normal severity scoring.

## Vendor Clarification SLA
Vendors must respond to a clarification request within the deadline tied to severity:
HIGH severity — 3 business days, MEDIUM — 5 business days, LOW — 7 business days. No
response by the deadline auto-escalates to the Procurement Manager.

## Audit Trail Requirement
Every disposition decision — Approve, Escalate, Reject, or Clarify — must record the
classification method, confidence score, and (when applicable) the specific contract or
policy clause cited as grounds for the decision. Decisions without a traceable basis are not
considered audit-compliant.
