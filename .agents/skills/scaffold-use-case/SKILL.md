---
name: scaffold-use-case
description: Scaffold a focused Clean Architecture use case with contracts and tests.
argument-hint: "[use-case name and behavior]"
disable-model-invocation: true
allowed-tools: Read, Grep, Glob, Edit, Write, Bash
---

Scaffold this use case:

$ARGUMENTS

Before editing, inspect the existing package layout and conventions. Create only the required domain, application, adapter, entrypoint, and test files. Define consumer-owned protocols, explicit boundary mapping, typed errors, and tests. Do not create empty layers or abstractions without demonstrated need.
