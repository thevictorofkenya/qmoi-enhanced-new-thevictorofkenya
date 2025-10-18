#!/usr/bin/env python3
"""
sync_orchestrator.py

Clean, robust orchestrator used by the repository's GitHub Actions workflows.

This script attempts to create a pull request on the upstream repository using the
fork head format "<public_owner>:<branch>". If GitHub rejects the head as invalid
(HTTP 422), the script will try to push the current HEAD to the upstream repository
using the provided UPSTREAM_PAT and then create the PR using the same-repository
branch name.

Outputs debug files under /tmp:
- /tmp/sync_orchestrator_result.json  (concise result)
- /tmp/sync_orchestrator_full.json    (full attempt log)

Usage: python3 scripts/sync_orchestrator.py <public_owner> <branch> <sha>
Environment variables required:
- UPSTREAM_PAT: token with repo access for the upstream (needs repo write if pushing)
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


def http_get(url, token):
    req = urllib.request.Request(url, method='GET')
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
    remote_url = f"https://x-access-token:{token}@github.com/{upstream_owner}/{upstream_repo}.git"
    details = {"remote_url_masked": f"https://x-access-token:***@github.com/{upstream_owner}/{upstream_repo}.git"}

    # Add a temporary remote and push
    rc, out, err = run_cmd(f'git remote add upstream {remote_url}')
    details['add_remote'] = {'rc': rc, 'out': out, 'err': err}
    # rc may be non-zero if remote already exists; continue anyway

    rc, out, err = run_cmd(f'git push upstream HEAD:refs/heads/{branch} --no-verify')
    details['push'] = {'rc': rc, 'out': out, 'err': err}

    # try to remove the remote (best-effort)
    run_cmd('git remote remove upstream')

    success = rc == 0
    return success, details


def main():
    if len(sys.argv) < 4:
        print('usage: sync_orchestrator.py <public_owner> <branch> <sha>', file=sys.stderr)
        sys.exit(2)

    public_owner = sys.argv[1]
    branch = sys.argv[2]
    sha = sys.argv[3]

    token = os.environ.get('UPSTREAM_PAT')
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
    }

    if not token:
        err = 'UPSTREAM_PAT not set in environment'
        print(err, file=sys.stderr)
        result['errors'].append(err)
        save_json(result_path, result)
        sys.exit(1)

    upstream_owner = 'thealphakenya'
    upstream_repo = 'qmoi-enhanced'
    upstream_api = f'https://api.github.com/repos/{upstream_owner}/{upstream_repo}'

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
        remote_url = f"https://x-access-token:{token}@github.com/{upstream_owner}/{upstream_repo}.git"
        details = {"remote_url_masked": f"https://x-access-token:***@github.com/{upstream_owner}/{upstream_repo}.git"}

        # Add a temporary remote and push
        rc, out, err = run_cmd(f'git remote add upstream {remote_url}')
        details['add_remote'] = {'rc': rc, 'out': out, 'err': err}
        # rc may be non-zero if remote already exists; continue anyway

        rc, out, err = run_cmd(f'git push upstream HEAD:refs/heads/{branch} --no-verify')
        details['push'] = {'rc': rc, 'out': out, 'err': err}

        # try to remove the remote (best-effort)
        run_cmd('git remote remove upstream')

        success = rc == 0
        return success, details


    def main():
        if len(sys.argv) < 4:
            print('usage: sync_orchestrator.py <public_owner> <branch> <sha>', file=sys.stderr)
            sys.exit(2)

        public_owner = sys.argv[1]
        branch = sys.argv[2]
        sha = sys.argv[3]

        token = os.environ.get('UPSTREAM_PAT')
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
        }

        if not token:
            err = 'UPSTREAM_PAT not set in environment'
            print(err, file=sys.stderr)
            result['errors'].append(err)
            save_json(result_path, result)
            sys.exit(1)

        upstream_owner = 'thealphakenya'
        upstream_repo = 'qmoi-enhanced'
        upstream_api = f'https://api.github.com/repos/{upstream_owner}/{upstream_repo}'

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
