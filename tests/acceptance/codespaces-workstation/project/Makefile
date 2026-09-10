.PHONY: verify increment export-artifact

verify:
	@test "$$(id -u)" -ne 0
	@command -v make >/dev/null
	@command -v rsync >/dev/null
	@command -v tar >/dev/null
	@printf 'codespaces workstation verified: uid=%s arch=%s\n' "$$(id -u)" "$$(uname -m)"

increment:
	@mkdir -p .generated
	@count=0; test ! -f .generated/count || count=$$(cat .generated/count); \
		count=$$((count + 1)); printf '%s\n' "$$count" > .generated/count; \
		printf 'incremental workstation count=%s\n' "$$count"

export-artifact: verify
	@mkdir -p dist
	@printf 'provider-native Codespaces OCI acceptance\n' > dist/result.txt
