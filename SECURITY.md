# Security Policy

## Scope

AgentMemory is currently a local-first public alpha project.

Memory content may include sensitive project, user, or agent data. Treat local runtime exposure and shared machine access accordingly.

## Reporting A Security Issue

Please do not open public issues for sensitive security reports.

Instead:

- contact the maintainer privately if possible
- include reproduction details, affected surface, and impact
- state whether the issue affects local-only use, Docker deployment, or MCP/HTTP exposure

## Current Security Posture

- local-first by design
- not positioned as a hosted multi-tenant service
- auth and remote exposure should be treated cautiously

## Out Of Scope For Public Claims

Until documented otherwise, the project should not be described as:

- hardened for hostile multi-tenant environments
- production-ready for open network exposure
- a managed hosted security boundary
