---
vendor_id: V-0011
vendor_name: Blair PLC
industry: Automotive Parts
contract_type: EDI Integration Agreement
effective_date: 2024-04-01
---

# Contract Terms — Blair PLC (V-0011)

## EDI Integration Note
Blair PLC is integrated via direct EDI feed rather than manual invoice entry. Per the
integration setup notes, the EDI feed does not always populate a GL Code field on the
invoice side — GL Code is expected to default to the GL Code on file from the originating
PO when blank on an EDI-sourced invoice. A blank GL Code from this vendor is a known
integration quirk, not missing data requiring vendor clarification, as long as the PO side
has a valid GL Code.

## Escalation Notes
If the PO side is ALSO missing a GL Code, this is a genuine Missing Fields exception and
should be routed normally.
