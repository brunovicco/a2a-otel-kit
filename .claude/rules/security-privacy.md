# Security and privacy rules

- Never access or expose `.env`, credentials, private keys, tokens, cloud profiles, or secret-manager output.
- Use least privilege and deny by default.
- Validate and constrain all external input, file paths, sizes, types, URLs, and identifiers.
- Use parameterized queries and safe serialization.
- Do not log personal data, secrets, authentication headers, prompts, model responses, or complete
  payloads. Any content-bearing tracing requires an explicit project policy, approval, redaction,
  retention, and access controls; tracing stays metadata-only otherwise.
- Do not use production personal data in development or tests.
- Record purpose, retention, deletion, access, and processors for personal data.
- New dependencies require vulnerability, maintenance, provenance, and license review.
- Security findings are not dismissed without evidence and an explicit risk decision.
