# Claude Project Instructions

Follow the repository guidance in [AGENTS.md](AGENTS.md).

## Server Operations

- The production LXC is reachable through the SSH host alias `test-vscode-tunnel`.
- VPM and Fux run as systemd services, not Docker containers. Check them with
  `ssh test-vscode-tunnel 'systemctl status vpm_bot.service fux.service'`.
- Both services should be `active` and `enabled`; VPM's service name is
  `vpm_bot.service`.
