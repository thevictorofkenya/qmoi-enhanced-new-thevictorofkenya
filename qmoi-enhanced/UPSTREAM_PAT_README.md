UPSTREAM_PAT READMEUPSTREAM_PAT README



This repository's sync automation requires a GitHub token stored as the Actions secret `UPSTREAM_PAT`.This repository's sync automation requires a GitHub token stored as the Actions secret `UPSTREAM_PAT`.



Minimum guidance:Minimum guidance:



1) Token type1) Token type

   - Either a classic Personal Access Token (PAT) with the `repo` scope (for private repos),   - Either a classic Personal Access Token (PAT) with the `repo` scope (for private repos),

     or a fine-grained Personal Access Token that includes Code: Read & Write for the upstream repository.     or a fine-grained Personal Access Token that includes Code: Read & Write for the upstream repository.



2) Token owner permissions2) Token owner permissions

   - The account that owns the token MUST have push access to the upstream repository `thealphakenya/qmoi-enhanced`.   - The account that owns the token MUST have push access to the upstream repository `thealphakenya/qmoi-enhanced`.

   - If that repository belongs to an organization that enforces SSO, the token owner must have approved SSO for that org.   - If that repository belongs to an organization that enforces SSO, the token owner must have approved SSO for that org.



3) Where to put the token3) Where to put the token

   - Add the token to this fork's repository secrets: Settings → Secrets → Actions → New repository secret   - Add the token to this fork's repository secrets: Settings → Secrets → Actions → New repository secret

     - Name: UPSTREAM_PAT     - Name: UPSTREAM_PAT

     - Value: <token>     - Value: <token>



4) Testing4) Testing

   - After adding the secret, trigger the `debug/trigger-workflow` by pushing a small commit to that branch.   - After adding the secret, trigger the `debug/trigger-workflow` by pushing a small commit to that branch.

   - The workflow performs a git ls-remote check as a pre-flight and will fail early if the token can't access the upstream.   - The workflow performs a git ls-remote check as a pre-flight and will fail early if the token can't access the upstream.



5) Security5) Security

   - Never commit real tokens to the repository. Use Actions secrets.   - Never commit real tokens to the repository. Use Actions secrets.

   - Prefer rotating the token periodically, and consider using a GitHub App for production sync (more secure).   - Prefer rotating the token periodically, and consider using a GitHub App for production sync (more secure).

