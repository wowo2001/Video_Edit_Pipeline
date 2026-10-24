"""Aggregate actual LLM usage; monetary estimates use recorded project rates."""
from datetime import datetime, timezone
from core.utils import read_json, write_json


def summarize(root):
    calls = []
    totals = {}
    for path in sorted(root.rglob('llm_cost_report.json')):
        for original in read_json(path).get('calls', []):
            call = dict(original, report=str(path.relative_to(root)))
            calls.append(call)
            currency = call.get('pricing', {}).get('currency')
            if currency and call.get('cost') is not None:
                totals[currency] = totals.get(currency, 0) + call['cost']
    result = {'updated_at': datetime.now(timezone.utc).isoformat(),
              'scope': 'LLM only: provider-reported tokens, estimated cost using project rates; not an invoice',
              'estimated_llm_totals': {k: round(v, 8) for k, v in totals.items()},
              'calls': calls,
              'excluded_costs': {'speech_recognition': 'Not priced; see each source audio duration and provider bill',
                                 'speech_synthesis': 'Not priced; see generated scripts/audio and provider bill',
                                 'other': 'Download, storage, local rendering and upload not priced'}}
    write_json(result, root / 'cost_summary.json', ensure_ascii=False, indent=2)
    return result
