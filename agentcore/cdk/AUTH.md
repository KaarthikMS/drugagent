# Authentication

```
Browser
  │  Cognito Hosted UI, work email only
  ▼  JWT (id token, 8h)
API Gateway  — JWT authorizer: signature, issuer, audience, expiry
  ▼  sub
Chat proxy Lambda  — signs SigV4, derives the session id from `sub`
  ▼
AgentCore Runtime
```

## Before you deploy

**Set the email domain.** `agentcore/cdk/cdk.json` ships a placeholder:

```json
"context": { "allowedEmailDomains": "REPLACE_WITH_YOUR_DOMAIN.com" }
```

Replace it, or pass it per-deploy:

```bash
cdk deploy -c allowedEmailDomains=company.com
```

With no domain set the auth stack is **not built at all** — the runtime stays
IAM-reachable and nothing else changes. That is deliberate: a pool deployed
without a domain would reject every sign-up, and a half-built auth path is worse
than none.

## After deploying

```bash
scripts/write-frontend-config.sh          # reads the stack outputs
aws cognito-idp admin-create-user \
  --user-pool-id <UserPoolId> \
  --username someone@company.com \
  --user-attributes Name=email,Value=someone@company.com Name=email_verified,Value=true
```

Then upload `frontend/` to the site bucket and invalidate the distribution.

## The decisions, and why

**Admin-invite only.** Self sign-up plus a domain check still admits anyone
holding a company address, including people who have left. A hundred known
employees is a list, not a funnel.

**Authorization code with PKCE, implicit disabled.** The implicit flow returns
the token in the URL fragment, where it lands in browser history and in any
referrer header. PKCE is what lets a browser complete a code exchange without a
client secret it could not keep anyway.

**8-hour tokens, 30-day refresh.** Health questions are occasional. A shorter
token limits what a stolen one is worth without making people log in twice a day.

**Tokens in memory, never localStorage.** localStorage survives the tab and is
readable by any script on the page, so an XSS walks away with eight hours of
access. In a module variable, a reload costs a silent redirect and leaves
nothing behind. The PKCE verifier does use sessionStorage: it must survive
exactly one redirect and is useless without the matching request.

**The session id is derived, never sent.**

```python
session_id = "u-" + hashlib.sha256(sub.encode()).hexdigest()
```

This is the line the whole design is for. A client-supplied session id is a
request to join a conversation, which becomes reading someone else's history the
moment AgentCore Memory is enabled. Validating its shape makes it unguessable;
deriving it from the authenticated subject makes it **owned**.

It is hashed because the session id appears in logs and traces, and a raw
Cognito `sub` there is a durable handle on a named employee.

**A PreSignUp trigger for the domain, not a pool setting.** A user pool has no
attribute constraint that can express "only @company.com". The trigger fails
**closed**: an empty allow-list rejects every sign-up, because the safe reading
of "no domains configured" is none, not all.

**CSP `connect-src` is the hosting control that matters.** An injected script can
run, but it can only reach Cognito and this account's API — not an attacker's
collection endpoint. Health questions cannot leave the two hosts meant to see
them.

## What this replaced

`app/drugagent/server.py`, a local FastAPI proxy that signed the same call with a
developer's AWS credentials and had no authentication in front of it. It existed
because a browser cannot produce SigV4. API Gateway plus the proxy Lambda is the
same job, done by something that checks who is asking.
