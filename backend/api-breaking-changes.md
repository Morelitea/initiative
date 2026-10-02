# Accepted API breaking changes

`scripts/ci/api-compat` compares this tree's OpenAPI spec with the last
release's and fails on a change that breaks a client written against that
release, unless the change is listed here. Each entry is the method, path and
message the check printed, under the release it ships in. An entry for a
release that has shipped no longer matters, and can be deleted.

## After 0.74.0

- POST /api/v1/c/{guild_id}/documents/{document_id}/copy api path removed without deprecation
