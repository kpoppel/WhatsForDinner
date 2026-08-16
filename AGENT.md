# AGENT Instructions for WhatsForDinner

These rules apply to all coding agents in this workspace.
If any rule conflicts with your default behavior, follow this file.

## Priority Order

1. Follow the user request exactly.
2. Keep changes minimal and focused.
3. Fix root causes, not symptoms.

## Non-Negotiable Rules

1. No fallback code.
- Do not add alternate execution paths, backup behaviors, silent defaults, or compatibility-only branches.
- If a fallback seems necessary, stop and ask the user how to proceed.
- NEVER introduce || [],  || {}, ? or ?? (nullable coalescing, papering over root cause issues)

2. Minimal scope only.
- Change only what is required for the requested outcome.
- Do not refactor adjacent code unless the user asks for it.
- If the fix requires broader impact, stop and ask for approval before widening scope.

3. No papering over API or data contract issues.
- Do not introduce aliases, shims, duplicate keys, or hidden data reshaping to make broken inputs appear valid.
- Correct the authoritative source of truth instead: API contract, schema, config key, or core logic.

## Decision Protocol

When blocked or when scope would expand:

1. Stop coding.
2. State exactly what blocks completion.
3. Present the smallest root-cause options.
4. Ask the user which option to take.

## Concrete Example

Case: required env key is TANDOOR_TOKEN_VALID_DATE, but code expects a misspelled key.

- Correct behavior: update code and env files to use TANDOOR_TOKEN_VALID_DATE only.
- Incorrect behavior: add TANDOOR_TOKEN_ALID_DATE as an alias for compatibility.

If correcting the key causes downstream breakage, do not add fallback handling. Ask the user how they want to proceed.

## Pre-Completion Checklist

Before finishing any task, verify:

1. No fallback behavior was introduced.
2. No unrequested scope expansion was made.
3. No alias/shim workaround was added.
4. The implemented change addresses the root cause.
