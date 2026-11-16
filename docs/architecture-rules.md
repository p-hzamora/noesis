# Architecture rules

Project-wide rules that bind every change. Each rule has its own section: what it says, why it
exists, and how it is enforced. A new rule is added here when the user or the design declares
it; the [architecture](architecture.md) page describes how the code applies them.

## Cross-context integration (D-003)

Decided in chunk C2 (`c2-core-model-neo4j-store`, D-003, confirmed as a project rule by D-021).

**Rule.** Bounded contexts integrate only through JSON-native contracts:

1. The providing context publishes a contract under `noesis/shared_kernel/contracts/<publisher>/`.
   It is a data-only model of JSON-native fields and carries a `contract_version`.
2. The consuming context owns a port, typed with those contracts, in its own application layer.
3. An inbound adapter of the providing context satisfies that port. The composition root
   (`interfaces/cli/bootstrap/`) wires the adapter into the consumer.
4. No context imports another, and no import-linter exception is allowed.

**Why.** Contexts can be built, tested and retired independently (the strangler migration from
Notes to Knowledge is finished). The contract is the only shared language, so a change to it is visible,
versioned and reviewable.

**Recorded exception (A-10).** Naming a kernel package after its publisher
(`contracts/<publisher>/`) deliberately bends "keep the shared kernel small". It is accepted
because the alternative is a context importing another's types.

**Enforced by.** `pyproject.toml` contracts "Bounded contexts are independent (they share only
the kernel's contracts)" and "Kernel contracts import no bounded context". Version discipline
and the wiring are checked in review.

## Dependencies point inward

Interfaces -> infrastructure -> application -> domain, per context and in the shared kernel.
Each layer may import only the layers to its right.

**Enforced by.** The layers contracts "Shared kernel layers point inward", "Diagnostics layers
point inward", "Knowledge layers point inward", "Retrieval layers
point inward" and "Capture layers point inward".

## Nothing below the interface layer imports it

`core`, `diagnostics`, `exceptions`, `shared_kernel`, `utils` and the bounded contexts never
import `noesis.interfaces`, and a bounded context never imports `noesis.core` or `typer`.

**Enforced by.** "Nothing below the interface layer imports it" and "Bounded contexts never
import the interfaces".

## Configuration is read only through `noesis.core.env`

The interfaces get settings from `noesis.core.env` and never import
`noesis.core.configurations` or `pydantic_settings`. Secrets (for example
`NOESIS_NEO4J_PASSWORD`) are read only from a user-side profile or the environment
(ADR-0001, Amendment 3).

**Enforced by.** "Configuration is read only through noesis.core.env".

## Domain and application stay free of frameworks and I/O

Domains import no `typer`, `subprocess`, `pydantic_settings` or `noesis.core`. Domain and
application layers import no `yaml`, `subprocess`, `shutil`, `tempfile` or
`noesis.shared_kernel.infrastructure`, and no `neo4j` driver. Adapters in infrastructure do
all I/O.

**Enforced by.** "Domain stays free of delivery and process frameworks", "Domain and application
layers stay free of I/O libraries" and "The graph driver stays in infrastructure".

## Diagnostics knows no bounded context

`noesis.diagnostics` imports no bounded context, `noesis.core`, `noesis.interfaces` or `typer`;
the composition root hands it plain values.

**Enforced by.** "Diagnostics knows no bounded context and no settings".
