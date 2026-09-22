"""Stable synthetic traces for window/cache and continuation tests."""
from __future__ import annotations
from copy import deepcopy
from . import DATASET_VERSION

def cache_trace():
    return {
      "trace_id":"invoice-window-trace-v1",
      "dataset_version":DATASET_VERSION,
      "project":"Synthetic InvoiceFlow continuation; no real customer data or external actions.",
      "windows":[
        {"goal":"Implement invoice tax rounding while preserving explicit product decisions and verified contract facts.",
         "events":[
           {"id":"h01","text":"User decision: money rounding uses Decimal ROUND_HALF_UP, never binary float round()."},
           {"id":"h02","text":"User decision: tax is rounded per invoice line before line totals are summed."},
           {"id":"h03","text":"Verified API contract: persisted tax output field is tax_minor."},
           {"id":"h04","text":"Assistant speculation said bankers rounding might be conventional; this was not approved."}],
         "turns":[
           {"q":"Which rounding policy is authoritative?","choices":["half_up","half_even","float_round"],"gold":"half_up"},
           {"q":"When is tax rounded?","choices":["per_line","after_total","never"],"gold":"per_line"},
           {"q":"Which persisted field is verified?","choices":["tax_minor","tax","amount_tax"],"gold":"tax_minor"},
           {"q":"Does the assistant speculation override the user decision?","choices":["yes","no"],"gold":"no"}]},
        {"goal":"Continue the same invoice work after a schema revision; retain earlier product decisions unless explicitly superseded.",
         "events":[
           {"id":"h05","text":"Repository moved to schema revision rev-B; old rev-A notes remain historical only."},
           {"id":"h06","text":"Verified rev-B migration maps internal tax_minor to JSON field taxMinor at the API boundary."},
           {"id":"h07","text":"A stale rev-A document still names JSON field tax_minor; it is superseded for the API boundary."},
           {"id":"h08","text":"Current tests still require ROUND_HALF_UP per line; no rounding decision was superseded."}],
         "turns":[
           {"q":"Which JSON field belongs to current rev-B API output?","choices":["taxMinor","tax_minor","tax"],"gold":"taxMinor"},
           {"q":"Did rev-B supersede the rounding policy?","choices":["yes","no"],"gold":"no"},
           {"q":"Which revision is current?","choices":["rev-A","rev-B"],"gold":"rev-B"},
           {"q":"Should the stale rev-A field name drive the current API patch?","choices":["yes","no"],"gold":"no"}]},
        {"goal":"Finish the tax patch and review it against all still-active decisions from earlier windows.",
         "events":[
           {"id":"h09","text":"Current patch candidate converts Decimal cents to integer tax_minor before API serialization."},
           {"id":"h10","text":"Review note: internal storage stays tax_minor even though rev-B API JSON uses taxMinor."},
           {"id":"h11","text":"A failing test was traced to rounding after summation instead of per-line rounding."},
           {"id":"h12","text":"No user message has revoked the earlier ROUND_HALF_UP requirement."}],
         "turns":[
           {"q":"What must be fixed in the failing tax calculation?","choices":["round_per_line","round_after_sum","use_float"],"gold":"round_per_line"},
           {"q":"Which internal field remains correct?","choices":["tax_minor","taxMinor","tax"],"gold":"tax_minor"},
           {"q":"Which external JSON field is current?","choices":["taxMinor","tax_minor","amount_tax"],"gold":"taxMinor"},
           {"q":"Is ROUND_HALF_UP still active?","choices":["yes","no"],"gold":"yes"}]}
      ]}

def coding_tasks():
    return [
      {"task_id":"rounding-continuation",
       "goal":"Choose the patch that preserves prior invoice rounding and current schema decisions.",
       "history":[
         {"id":"c01","text":"User decision: monetary values use Decimal ROUND_HALF_UP."},
         {"id":"c02","text":"User decision: round each line before summing."},
         {"id":"c03","text":"Old prototype used Python round(float(...)); it was rejected after a 1.005 regression."},
         {"id":"c04","text":"Current schema stores tax_minor as integer cents."},
         {"id":"c05","text":"Unrelated note: invoice PDF font fallback was changed."},
         {"id":"c06","text":"Assistant once proposed ROUND_HALF_EVEN; user did not approve it."}],
       "current_code":"def tax_total(values):\n    return round(sum(float(v) for v in values), 2)\n",
       "patches":{
         "A":"Use float round() on each line, then sum.",
         "B":"Convert each value through Decimal(str(v)), quantize each line with ROUND_HALF_UP to 0.01, then sum.",
         "C":"Use Decimal ROUND_HALF_EVEN on the final total.",
         "D":"Sum Decimal values first, then ROUND_HALF_UP once at the end."},
       "expected":"B"},
      {"task_id":"retry-continuation",
       "goal":"Choose the retry patch consistent with prior payment-safety decisions after an ambiguous timeout.",
       "history":[
         {"id":"p01","text":"User decision: a network timeout is not proof that the payment was not charged."},
         {"id":"p02","text":"User decision: persist the idempotency key before the first send and reuse it for the same logical payment."},
         {"id":"p03","text":"Provider contract exposes a read-only status lookup by persisted idempotency key."},
         {"id":"p04","text":"Old prototype generated a new idempotency key after timeout; review rejected that behavior."},
         {"id":"p05","text":"Current incident: request bytes were sent, then the connection reset before a response arrived."},
         {"id":"p06","text":"Unrelated note: receipt email retry policy changed independently."}],
       "current_code":"def next_action(timeout, key):\n    if timeout:\n        return ('retry', new_key())\n",
       "patches":{
         "A":"Immediately resend with a newly generated idempotency key.",
         "B":"Query read-only status using the persisted key; only resend the same logical payment with that same key if status proves no charge.",
         "C":"Assume timeout means no charge and retry with the persisted key without checking status.",
         "D":"Never retry or inspect status after any timeout."},
       "expected":"B"}
    ]

def clone(x):
    return deepcopy(x)
