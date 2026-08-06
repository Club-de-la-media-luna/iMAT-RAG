# Material arrives from contributor-owned repositories, not organisation members

A contributor duplicates a public, empty template into **their own** namespace,
keeps it private, drops files into `<COURSE>/<kind>/`, and grants a maintainer
read access. `rag inbox <repo>` copies what is filed correctly into
`master_kb`, writes the bibliography ledger entries, and records the source in
`sources.json`. Nobody is added to the `Club-de-la-media-luna` organisation in
order to contribute material.

## Considered Options

**Inviting contributors into the organisation** was the obvious approach and is
the one the Hub is designed around. It fails on the free tier's permission
model. Roles are organisation-wide, and per-repository access
([Resource Groups](https://huggingface.co/docs/hub/security-resource-groups))
is a Team/Enterprise feature. So:

- `contributor` grants write only to repositories the member created — safe,
  but it means each contributor creates their own repository anyway, so the
  organisation gains nothing but a membership list.
- `write`, which is what a *shared* inbox repository would require, grants
  write to **every** repository in the organisation, including
  `master_kb-derived`. A contributor who drags a folder into the wrong
  repository can delete or overwrite the published index. The index is 173 MB
  and 25 minutes of GPU time, and the mistake takes two seconds.

Contributor-owned repositories also move the moment of acceptance. Material
sits in somebody else's namespace until a maintainer runs `rag inbox`, so this
organisation never hosts anything nobody has looked at.

## Consequences

**The upstream repository is disposable.** `rag inbox` copies rather than
references, precisely because the source belongs to an account this project
does not control and may be deleted, emptied or revoked. What is lost when that
happens is only material nobody has taken yet.

**The privacy mistake moves out of sight, so the tool enforces it.** When we
owned the inbox, its visibility was set once by an admin. Now each contributor
chooses, and "leave it public" is exactly the error a non-technical contributor
makes. Documentation cannot prevent it, so `rag inbox` refuses to read from a
public repository at all. Duplicating the template rather than creating a fresh
repository helps too: visibility is chosen in the same dialog as the name,
rather than being a separate setting to overlook.

**Discovery becomes explicit.** With one organisation-owned inbox, ingestion
could enumerate repositories. Now the maintainer registers each source, and
`sources.json` is tracked in `master_kb` git — which is the group's record of
where its corpus came from, and is worth having for its own sake.

**The ingest step is the trust boundary.** Everything taken is embedded into an
index published to the whole group, so the moment to look at what is being
accepted is `rag inbox`, not upload time. It therefore refuses rather than
guesses: unknown course codes, unknown tiers, files without a folder, anything
under 20 pages, and any path that climbs out of its own directory — the tree
comes from a repository nobody here controls.
