# Sheet-review baseline

CLI: 2.1.325
Fixture SHA-256: `af602c8ceb802bdd8c4b3c402d8cc9bd70172f8961b2d7c10bb085e601bdbfd2`

| Condition | Status | Messages | Failed tool calls | Total tokens | Duration ms | First skill |
|---|---|---:|---:|---:|---:|---|
| with skills | timeout | 27 | 2 |  |  | arch-eval:sheet-review |
| without skills | not run | n/a | n/a | n/a | n/a | n/a |

Messages = submitted prompt + unique assistant messages + emitted user/tool-result messages.
Total tokens = input + output + cache creation input + cache read input, from the result event.
Failed tool calls count unique tool_result IDs with is_error=true; session errors are separate.
Both conditions receive identical prompts, fixture bytes and PDF scripts. Only the second adds
--disable-slash-commands. No app or MCP tools are available. Shell permission is limited to python3.
This is a single pair, not a statistical result. Resource counts alone do not establish quality.

Pair validity: incomplete; stopped before the second session.
