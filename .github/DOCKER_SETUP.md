# Container Image Publishing

Initiative's image is published to the GitHub Container Registry as
`ghcr.io/beyonders-studio/initiative`. This explains how it gets there and the
one-time setup it needs.

## How it works

Every workflow that pushes or retags the image (`docker-image.yml` and its
callers `dev-build.yml`, `release-candidate.yml` and `docker-publish.yml`, plus
`promote-stable.yml`) logs in to `ghcr.io` with the job's own `GITHUB_TOKEN`.
The calling job grants that token `packages: write`; there is no registry
secret to create or rotate. The repository is `ghcr.io/<owner>/initiative`,
the owner lowercased, so a fork publishes to its own namespace.

The build stamps the OCI `org.opencontainers.image.source` label, which links
the package to this repository: its page is
<https://github.com/beyonders-studio/initiative/pkgs/container/initiative>.

## One-time setup

A new GHCR package is **private**. After the first push (the first Dev Build
on `dev`), an org owner opens the package's **Package settings** and sets its
visibility to **Public**, once. Until then nobody can pull it without a token,
and the workflows that inspect or pull it anonymously (the release's candidate
lookup, the upgrade walk, the browser journeys) fail.

## Tags

| Tag | Moved by | Points at |
|-----|----------|-----------|
| `dev-<sha>` | Dev Build | that commit on `dev` |
| `dev` | Dev Build | the tip of `dev` |
| `unchecked-<tree>`, `candidate-<tree>` | Release Candidate | a release branch's build, before and after its walk |
| `X.Y.Z`, `X.Y`, `X`, `latest` | Build and Release | the release |
| `stable` | Promote Stable | a release that has soaked |

```bash
docker pull ghcr.io/beyonders-studio/initiative:latest
docker pull ghcr.io/beyonders-studio/initiative:0.74.0
```

Images are multi-arch (`linux/amd64`, `linux/arm64`), signed keylessly with
cosign, and carry an SBOM and build provenance; the command to verify one is in
`docs/en/running-a-server/installation.md`.

## Troubleshooting

- **`denied: permission_denied` on push**: the calling job is missing
  `packages: write`, or the package's **Manage Actions access** does not give
  this repository write access.
- **`unauthorized` on an anonymous pull or inspect**: the package is still
  private; see One-time setup.
