# Security policy

## Supported versions

Security fixes are made on the latest released minor version. Older development
snapshots are not maintained as separate security branches.

## Reporting a vulnerability

Do not open a public issue for a suspected vulnerability. Use GitHub's private
security-advisory form for this repository:

https://github.com/jianwen-zhu/cloudmake/security/advisories/new

Include the affected backend, Cloudmake version, reproduction conditions, and
potential impact. Remove provider credentials, private source, access tokens,
and account identifiers from logs before attaching them.

Cloudmake executes project code on third-party infrastructure. Provider outages,
quota decisions, and vulnerabilities in provider images should be reported to
the relevant provider unless Cloudmake's transfer, command construction, local
state, or artifact handling contributes to the issue.
