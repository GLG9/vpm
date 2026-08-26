# Claude Project Instructions

Follow the repository guidance in [AGENTS.md](AGENTS.md).

## Server Operations

- The production LXC is reachable through the SSH host alias `test-vscode-tunnel`.
- `ssh test-vscode-tunnel 'docker ps'` shows the deployed `vpm` and `fux`
  containers. Use this command first when checking their runtime state.
