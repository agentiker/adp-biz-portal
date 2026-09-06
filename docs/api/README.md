# Unified Platform API Contract

`openapi.yaml` is the versioned contract for the browser-facing `/api/v1` platform API. Internal `/api/internal/*` ADP service routes are deliberately excluded because they require a server-to-server token and are not a frontend contract.

Regenerate the TypeScript types after changing the contract:

```bash
make platform_api_types
```

Run the contract and generated-output checks before committing:

```bash
make platform_api_check
```

The check validates YAML structure, local `$ref` targets, operation metadata, parity with `/api/v1` routes declared in `server/router/platform.py`, and whether `client/packages/app/src/platform/generated.ts` is current. `types.ts` re-exports the generated models so application code consumes the contract-derived names.
