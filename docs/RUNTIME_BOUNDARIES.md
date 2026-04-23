# Runtime Boundaries

This document defines what AgentMemory owns and what it intentionally does not own.

## Core Position

AgentMemory is a runtime above memory providers.

It is not the layer that should decide what a user ought to remember, forget,
keep temporarily, or keep permanently.

## What AgentMemory Owns

AgentMemory owns runtime concerns:

- one stable contract above providers
- CLI / HTTP / MCP access surfaces
- typed validation and typed errors
- provider capability declarations
- provider runtime policy and routing
- provider-neutral portability helpers
- diagnostics, certification, and operational guidance
- optional lifecycle execution when the caller explicitly asks for it

In short:

- how memory is exposed
- how provider behavior is normalized
- how runtime semantics are enforced consistently

## What AgentMemory Does Not Own

AgentMemory does not own memory policy.

That includes:

- deciding what should be written to memory
- deciding whether something is semantically short-term or long-term
- choosing retention policy for arbitrary user domains
- assigning TTL based on guessed importance or guessed duration
- inventing universal memory categories for every workflow

In short:

- what should be remembered
- how long it should matter
- why that retention policy is correct

## Where TTL Fits

TTL is allowed in AgentMemory only as optional lifecycle support.

Correct interpretation:

- caller provides `metadata.ttl_seconds` or `metadata.expires_at`
- runtime stores and enforces that metadata consistently
- runtime hides and sweeps expired records according to the declared metadata

Incorrect interpretation:

- runtime guesses which memories are temporary
- runtime decides how long a memory should live by itself
- runtime tries to solve generalized memory-policy design for the user

## Why This Boundary Matters

Without this boundary, AgentMemory drifts away from runtime infrastructure and
toward a semantic memory product that it cannot reliably implement.

That would create:

- nondeterministic retention behavior
- domain-specific policy mistakes
- hidden product assumptions inside a runtime layer
- harder provider integration and weaker contracts

With this boundary, AgentMemory stays honest and stable:

- runtime executes declared semantics
- caller owns memory policy

## Practical Rule

If a feature requires understanding user intent, workflow duration, or the
meaning-level importance of a fact, it is probably outside runtime scope.

If a feature is about enforcing a declared contract consistently across
providers and transports, it is probably runtime scope.
