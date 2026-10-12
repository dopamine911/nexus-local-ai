#!/usr/bin/env python3
"""Record local OpenAI-compatible completion latency without storing prompts/responses."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import ipaddress
import json
from pathlib import Path
import ssl
import time
import urllib.parse
import urllib.request


def run_one(url, model, key, prompt, context):
    body = json.dumps({'model': model, 'messages': [{'role': 'user', 'content': prompt}],
                       'temperature': 0, 'max_tokens': 256, 'stream': False}).encode()
    request = urllib.request.Request(url.rstrip('/') + '/chat/completions', body,
                                    headers={'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json'})
    start = time.perf_counter()
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), urllib.request.HTTPSHandler(context=context))
    with opener.open(request, timeout=600) as response:
        data = json.load(response)
    elapsed = time.perf_counter() - start
    if not data.get('choices'):
        raise ValueError('No completion choices received')
    tokens = data.get('usage', {}).get('completion_tokens')
    return {'seconds': elapsed, 'completion_tokens': tokens,
            'end_to_end_tokens_per_second': tokens / elapsed if tokens else None}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', required=True, help='Local /v1 base URL; remote paid providers are refused')
    parser.add_argument('--model', required=True)
    parser.add_argument('--api-key-file', type=Path, required=True)
    parser.add_argument('--prompt-file', type=Path, required=True)
    parser.add_argument('--ca', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--runs', type=int, default=3)
    parser.add_argument('--concurrency', type=int, choices=(1, 2), default=1)
    args = parser.parse_args()
    parsed = urllib.parse.urlparse(args.url)
    hostname = parsed.hostname or ''
    try:
        address = ipaddress.ip_address(hostname)
        local = address.is_loopback or address in ipaddress.ip_network('100.64.0.0/10')
    except ValueError:
        local = hostname.endswith('.home.arpa')
    if not local or parsed.scheme not in ('http', 'https') or parsed.username or parsed.password or parsed.query or parsed.fragment:
        parser.error('Use a loopback, Tailscale IPv4 or home.arpa endpoint without URL credentials')
    if not 1 <= args.runs <= 20:
        parser.error('Use between 1 and 20 runs')
    if args.api_key_file.stat().st_mode & 0o077:
        parser.error('API-key file must have permissions 600')
    if args.output.exists():
        parser.error('Output exists; choose a new benchmark report')
    key = args.api_key_file.read_text().strip()
    prompt = args.prompt_file.read_text()
    context = ssl.create_default_context(cafile=str(args.ca) if args.ca else None)
    with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        results = list(pool.map(lambda _: run_one(args.url, args.model, key, prompt, context), range(args.runs)))
    report = {'created_at': datetime.now(timezone.utc).isoformat(), 'model': args.model,
              'prompt_sha256': hashlib.sha256(prompt.encode()).hexdigest(), 'concurrency': args.concurrency,
              'max_completion_tokens': 256, 'temperature': 0, 'runs': results}
    args.output.write_text(json.dumps(report, indent=2) + '\n')
    print(f'Wrote {args.runs} measured requests to {args.output}; prompt and response text omitted.')


if __name__ == '__main__':
    main()
