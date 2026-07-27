# NetCoreDbg

When a source breakpoint stays pending, inspect DAP `module` events for
`symbolStatus` and `breakpoint` events for resolved paths. Source Link may map
documents to virtual paths that do not match a local breakpoint; absent or
mismatched PDBs commonly report `Symbols not found.`

NetCoreDbg may reject evaluator forms such as interpolation, object creation,
lambdas, or some method calls. Prefer simple direct field or property
expressions. Treat these as adapter constraints; do not emulate them in aidbg.
