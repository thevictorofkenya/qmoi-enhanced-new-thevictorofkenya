#!/usr/bin/env python3
"""
sync_orchestrator.py

Cleaner, consolidated orchestrator used by the repository's GitHub Actions workflows.

Behavior summary:
- Verify the fork branch exists on the public fork before attempting to create a PR
  using the `owner:branch` head format. If the branch isn't present, write a clear
  error and exit.
- Attempt to create a PR on the private upstream using the fork head. If GitHub
  responds with a 422 "head invalid" error, attempt to push the current HEAD to
  the upstream repo (using the provided token) and then create a same-repo PR.

Debug output (machine-readable) is written to /tmp:
- /tmp/sync_orchestrator_result.json  (concise result)
- /tmp/sync_orchestrator_full.json    (full attempt log)

Usage: python3 scripts/sync_orchestrator.py <public_owner> <branch> <sha>
Environment:
- UPSTREAM_PAT must be set (secret token stored in Actions as UPSTREAM_PAT).
"""

import json
import sys
import time
import os
import subprocess
import shlex
import urllib.request
import urllib.error


TIMEOUT = 15


def http_post(url, token, payload_obj):
    data = json.dumps(payload_obj).encode('utf-8')
    req = urllib.request.Request(url, data=data, method='POST')
    req.add_header('Authorization', f'token {token}')
    req.add_header('Accept', 'application/vnd.github.v3+json')
    req.add_header('Content-Type', 'application/json')
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            body = resp.read().decode('utf-8')
            return resp.getcode(), body
    except urllib.error.HTTPError as e:
        try:
            body = e.read().decode('utf-8')
        except Exception:
            body = ''
        return e.code, body
    except Exception as e:
        return None, str(e)


def http_get(url, token=None):
    req = urllib.request.Request(url, method='GET')
    if token:
        req.add_header('Authorization', f'token {token}')
    req.add_header('Accept', 'application/vnd.github.v3+json')
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            body = resp.read().decode('utf-8')
            return resp.getcode(), body
    except urllib.error.HTTPError as e:
        try:
            body = e.read().decode('utf-8')
        except Exception:
            body = ''
        return e.code, body
    except Exception as e:
        return None, str(e)


def save_json(path, data):
    try:
        with open(path, 'w') as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        print(f'Warning: failed to write {path}: {e}', file=sys.stderr)


def run_cmd(cmd, cwd=None, env=None, capture_output=True):
    """Run a shell command and return (rc, stdout, stderr)"""
    try:
        proc = subprocess.run(shlex.split(cmd), cwd=cwd, env=env, capture_output=capture_output, text=True, check=False)
        return proc.returncode, proc.stdout, proc.stderr
    except Exception as e:
        return None, '', str(e)


def push_branch_to_upstream(upstream_owner, upstream_repo, branch, token):
    """Attempt to push the current branch to the upstream repository using the provided token.

    Returns (success_boolean, details_dict)
    """
    # We'll avoid embedding the token into a stored remote URL. Use git's
    # http.extraheader to pass an Authorization header for the single push.
    push_url = f"https://github.com/{upstream_owner}/{upstream_repo}.git"
    details = {"push_url": push_url, "remote_url_masked": f"***github.com/{upstream_owner}/{upstream_repo}.git"}

    # Use an extraheader for a one-off authenticated push. Quoted header keeps
    # it as a single argv token when split by shlex.
    cmd = f'git -c http.extraheader="Authorization: Bearer {token}" push {push_url} HEAD:refs/heads/{branch} --no-verify'
    rc, out, err = run_cmd(cmd)
    details['push'] = {'rc': rc, 'out': out, 'err': err}

    # Interpret common failures and provide actionable hints
    if rc != 0:
        hint = None
        err_lower = (err or '').lower()
        if 'repository not found' in err_lower or "not found" in err_lower:
            hint = 'Upstream repository not found or token lacks access. Ensure UPSTREAM_PAT belongs to an account with push access to the upstream (and SSO-approved if the upstream is in an org).'
        elif 'authentication failed' in err_lower or 'could not read from remote repository' in err_lower or 'access denied' in err_lower:
            hint = 'Authentication failed. Verify the UPSTREAM_PAT has the correct scopes (repo write) and that the token owner has permission on the upstream repository.'
        if hint:
            details['hint'] = hint

    success = rc == 0
    return success, details


def check_branch_exists_on_public(public_owner, repo, branch, token=None):
    """Return (exists_boolean, details)

    This checks the public fork at /repos/{public_owner}/{repo}/branches/{branch}.
    If the public fork's repo name differs from the upstream repo name this will
    return False (caller can then provide guidance).
    """
    details = {}
    # First: if this is running in a checked-out repository (Actions), prefer
    # using local git to check the refs — it's fast and doesn't require API auth.
    rc, out, err = run_cmd(f'git rev-parse --verify --quiet refs/remotes/origin/{branch}')
    details['git_rev_parse'] = {'rc': rc, 'out': out, 'err': err}
    if rc == 0:
        details['body'] = 'branch exists (local origin ref)'
        return True, details

    # Fallback: ask the GitHub API (may require auth for private forks)
    url = f'https://api.github.com/repos/{public_owner}/{repo}/branches/{branch}'
    code, body = http_get(url, token)
    details['check_url'] = url
    details['http_code'] = code
    details['body'] = body
    if code == 200:
        return True, details
    return False, details


def main():
    if len(sys.argv) < 4:
        print('usage: sync_orchestrator.py <public_owner> <branch> <sha>', file=sys.stderr)
        sys.exit(2)

    public_owner = sys.argv[1]
    branch = sys.argv[2]
    sha = sys.argv[3]

    # Prefer an installation token from a GitHub App if present (safer), else fallback to UPSTREAM_PAT
    token = os.environ.get('INSTALLATION_TOKEN') or os.environ.get('UPSTREAM_PAT')
    debug_dir = '/tmp'
    result_path = os.path.join(debug_dir, 'sync_orchestrator_result.json')
    full_path = os.path.join(debug_dir, 'sync_orchestrator_full.json')

    result = {
        'public_owner': public_owner,
        'branch': branch,
        'sha': sha,
        'attempts': [],
        'created_pr_url': None,
        'existing_prs': [],
        'errors': [],
        'token_type': 'none',
    }

    if not token:
        err = 'UPSTREAM_PAT not set in environment'
        print(err, file=sys.stderr)
        result['errors'].append(err)
        save_json(result_path, result)
        sys.exit(1)
    else:
        if os.environ.get('INSTALLATION_TOKEN'):
            result['token_type'] = 'installation_token'
        else:
            result['token_type'] = 'upstream_pat'

    upstream_owner = 'thealphakenya'
    upstream_repo = 'qmoi-enhanced'
    upstream_api = f'https://api.github.com/repos/{upstream_owner}/{upstream_repo}'

    # First: verify the public fork contains the branch we're trying to use as head.
    exists, check_details = check_branch_exists_on_public(public_owner, upstream_repo, branch, token=None)
    result['public_branch_check'] = check_details
    if not exists:
        msg = (
            f"Branch '{branch}' not found on public fork {public_owner}/{upstream_repo}.\n"
            "Ensure the branch exists on the public fork and that the fork's repository name matches the upstream repo name."
        )
        result['errors'].append({'public_branch_missing': msg})
        save_json(result_path, result)
        print(msg, file=sys.stderr)
        sys.exit(1)

    # list open PRs
    list_url = f"{upstream_api}/pulls?state=open&per_page=100"
    code, body = http_get(list_url, token)
    result['list_prs_http_code'] = code
    try:
        prs = json.loads(body) if body else []
    except Exception:
        prs = []
        result['errors'].append('Failed parsing PR list')

    for p in prs:
        head_label = p.get('head', {}).get('label')
        if head_label == f"{public_owner}:{branch}":
            result['existing_prs'].append(p.get('html_url'))

    # write a snapshot of the list response
    save_json(full_path, {'list_prs_http_code': code, 'list_prs_body': prs})

    if result['existing_prs']:
        result['message'] = 'Existing PR(s) found'
        save_json(result_path, result)
        print('Existing PR found:', result['existing_prs'])
        sys.exit(0)

    # Attempt to create PR from fork head first
    create_url = f"{upstream_api}/pulls"
    head_from_fork = f"{public_owner}:{branch}"
    payload_obj = {
        'title': f'Sync from public repo: {sha}',
        'head': head_from_fork,
        'base': 'main',
        'body': f'Automated sync from public repo {public_owner}/{branch} ({sha}).'
    }

    max_attempts = 3
    sleep = 2
    for attempt in range(1, max_attempts + 1):
        code, body = http_post(create_url, token, payload_obj)
        entry = {'attempt': attempt, 'http_code': code, 'response_raw': body}
        try:
            entry['response'] = json.loads(body) if body else None
        except Exception:
            entry['response'] = body
        result['attempts'].append(entry)
        save_json(full_path, result)

        if code == 201:
            result['created_pr_url'] = entry['response'].get('html_url') if isinstance(entry['response'], dict) else None
            save_json(result_path, result)
            print('PR created:', result['created_pr_url'])
            sys.exit(0)

        # If head invalid (422 with head invalid) attempt alternative: push branch to upstream then create PR
        if code == 422 and isinstance(entry['response'], dict):
            errs = entry['response'].get('errors', [])
            invalid_head = any((isinstance(e, dict) and e.get('field') == 'head' and e.get('code') == 'invalid') for e in errs)
            if invalid_head:
                push_ok, push_details = push_branch_to_upstream(upstream_owner, upstream_repo, branch, token)
                result['push_attempt'] = push_details
                save_json(full_path, result)

                if push_ok:
                    # try creating PR with head set to the branch in the upstream repo (same-repo head)
                    payload_obj2 = dict(payload_obj)
                    payload_obj2['head'] = branch
                    code2, body2 = http_post(create_url, token, payload_obj2)
                    entry2 = {'attempt': attempt, 'http_code': code2, 'response_raw': body2}
                    try:
                        entry2['response'] = json.loads(body2) if body2 else None
                    except Exception:
                        entry2['response'] = body2
                    result['attempts'].append({'retry_after_push': entry2})
                    save_json(full_path, result)
                    if code2 == 201:
                        result['created_pr_url'] = entry2['response'].get('html_url') if isinstance(entry2['response'], dict) else None
                        save_json(result_path, result)
                        print('PR created after pushing branch to upstream:', result['created_pr_url'])
                        sys.exit(0)
                    else:
                        result['errors'].append({'push_pr_attempt': {'code': code2, 'response': entry2.get('response')}})
                        save_json(result_path, result)
                        print('PR creation after push failed; check details')
                        sys.exit(1)
                else:
                    result['errors'].append({'push_failed': push_details})
                    save_json(result_path, result)
                    print('Push to upstream failed; cannot create PR from upstream branch')
                    sys.exit(1)

        result['errors'].append({'attempt': attempt, 'http_code': code, 'response': entry.get('response')})
        if attempt < max_attempts:
            time.sleep(sleep)
            sleep *= 2

    save_json(result_path, result)
    print(f'Failed to create PR after {max_attempts} attempts; see {result_path}', file=sys.stderr)
    sys.exit(1)


if __name__ == '__main__':
    main()


    if __name__ == '__main__':
        main()
