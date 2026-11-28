# Source from the GitHub Actions runner.
test "$HOST" = 82.165.187.14
test -n "$KEY"
expected_fingerprint="${HOST_FINGERPRINT:-SHA256:G5zZTiYxEm6Hm2v/CYFe/4e7K3YwRCbOkABFBBy93vg}"
port="${SSH_PORT:-22}"
tmp="$(mktemp -d)"
trap 'if [ -n "${SSH_AGENT_PID:-}" ]; then ssh-agent -k >/dev/null 2>&1 || true; fi; rm -rf "$tmp"' EXIT
umask 077
printf '%s\n' "$KEY" | tr -d '\r' > "$tmp/key"
chmod 600 "$tmp/key"
if [ -n "$PASSPHRASE" ]; then
  eval "$(ssh-agent -s)" >/dev/null
  printf '%s\n' '#!/bin/sh' 'printf "%s\n" "$PASSPHRASE"' > "$tmp/askpass"
  chmod 700 "$tmp/askpass"
  DISPLAY=:0 SSH_ASKPASS="$tmp/askpass" SSH_ASKPASS_REQUIRE=force setsid ssh-add "$tmp/key" </dev/null >/dev/null
fi
unset PASSPHRASE KEY
ssh-keyscan -T 10 -t ed25519 -p "$port" "$HOST" > "$tmp/known_hosts" 2>/dev/null
test -s "$tmp/known_hosts"
actual_fp="$(ssh-keygen -E sha256 -lf "$tmp/known_hosts" | awk 'NR==1{print $2}')"
test "$actual_fp" = "$expected_fingerprint"
SSH=(ssh -i "$tmp/key" -o IdentitiesOnly=yes -o BatchMode=yes -o ForwardAgent=no -o StrictHostKeyChecking=yes -o UserKnownHostsFile="$tmp/known_hosts" -o GlobalKnownHostsFile=/dev/null -o ConnectTimeout=10 -p "$port")

# Read the complete script before invoking Compose so child processes cannot consume it.
host_release() {
  local operation=$1 revision=${2:-}
  [[ $operation =~ ^(preflight|rehearse|release|rollback)$ ]]
  [[ -z $revision || $revision =~ ^[a-f0-9]{40}$ ]]
  local remote_command
  printf -v remote_command 'script=$(cat); exec bash -euc "$script" -- %q %q' "$operation" "$revision"
  "${SSH[@]}" root@"$HOST" "$remote_command" < ops/taskservice/host-release.sh
}
