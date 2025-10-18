#!/usr/bin/env python3
"""
mint_installation_token.py

Example helper to mint a GitHub App installation token using the app's private key.
This is intended to be run inside a GitHub Actions job or on a secure admin machine.

Usage (example):
  python3 .github/apps/mint_installation_token.py --app-id 12345 --installation-id 67890 --private-key-file /tmp/app.pem

Outputs the token on stdout.

Dependencies: PyJWT (pyjwt) and requests
"""
import argparse
import time
import jwt
import requests

GITHUB_API = 'https://api.github.com'

def make_jwt(app_id, private_key_pem):
    now = int(time.time())
    payload = {
        'iat': now - 60,
        'exp': now + (10 * 60),
        'iss': app_id
    }
    return jwt.encode(payload, private_key_pem, algorithm='RS256')


def mint_token(app_id, installation_id, private_key_pem):
    jw = make_jwt(app_id, private_key_pem)
    headers = {
        'Authorization': f'Bearer {jw}',
        'Accept': 'application/vnd.github+json'
    }
    url = f'{GITHUB_API}/app/installations/{installation_id}/access_tokens'
    r = requests.post(url, headers=headers)
    r.raise_for_status()
    data = r.json()
    return data.get('token')


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--app-id', required=True, help='GitHub App id')
    p.add_argument('--installation-id', required=True, help='Installation id')
    p.add_argument('--private-key-file', required=True, help='Path to private key PEM')
    args = p.parse_args()

    with open(args.private_key_file, 'r') as f:
        key = f.read()

    token = mint_token(args.app_id, args.installation_id, key)
    print(token)
