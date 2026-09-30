# Accepted API breaking changes

`scripts/ci/api-compat` compares this tree's OpenAPI spec with the last
release's and fails on a change that breaks a client written against that
release, unless the change is listed here. Each entry is the method, path and
message the check printed, under the release it ships in. An entry for a
release that has shipped no longer matters, and can be deleted.

## After 0.73.2

- DELETE /api/v1/c/{guild_id}/apps/{app_id}/placements/{initiative_id} api removed without deprecation
- GET /api/v1/c/{guild_id}/calendar-entries/ added `subschema #1` to the `events/items/recurrence` response property `anyOf` list for the response status `200`
- GET /api/v1/c/{guild_id}/calendar-entries/ added `subschema #1` to the `tasks/items/recurrence` response property `anyOf` list for the response status `200`
- GET /api/v1/c/{guild_id}/calendar-events/ added `subschema #1` to the `items/items/recurrence` response property `anyOf` list for the response status `200`
- POST /api/v1/c/{guild_id}/calendar-events/ removed `#/components/schemas/EventRecurrence` from the `recurrence` request property `anyOf` list
- POST /api/v1/c/{guild_id}/calendar-events/ added `subschema #1` to the `recurrence` response property `anyOf` list for the response status `201`
- GET /api/v1/c/{guild_id}/calendar-events/{event_id} added `subschema #1` to the `recurrence` response property `anyOf` list for the response status `200`
- PATCH /api/v1/c/{guild_id}/calendar-events/{event_id} removed `#/components/schemas/EventRecurrence` from the `recurrence` request property `anyOf` list
- PATCH /api/v1/c/{guild_id}/calendar-events/{event_id} added `subschema #1` to the `recurrence` response property `anyOf` list for the response status `200`
- PUT /api/v1/c/{guild_id}/calendar-events/{event_id}/attendees added `subschema #1` to the `recurrence` response property `anyOf` list for the response status `200`
- PUT /api/v1/c/{guild_id}/calendar-events/{event_id}/properties added `subschema #1` to the `recurrence` response property `anyOf` list for the response status `200`
- PATCH /api/v1/c/{guild_id}/calendar-events/{event_id}/rsvp added `subschema #1` to the `recurrence` response property `anyOf` list for the response status `200`
- PUT /api/v1/c/{guild_id}/calendar-events/{event_id}/tags added `subschema #1` to the `recurrence` response property `anyOf` list for the response status `200`
- DELETE /api/v1/c/{guild_id}/dashboards/{dashboard_id}/published/{resource_type}/{resource_id} api path removed without deprecation
- GET /api/v1/c/{guild_id}/initiatives/{initiative_id}/join-requests/me api path removed without deprecation
- GET /api/v1/c/{guild_id}/property-definitions/{definition_id} api removed without deprecation
- GET /api/v1/c/{guild_id}/property-definitions/{definition_id}/entities api path removed without deprecation
- PUT /api/v1/c/{guild_id}/queues/{queue_id}/items/reorder api path removed without deprecation
- GET /api/v1/c/{guild_id}/tasks/ added `subschema #1` to the `items/items/recurrence` response property `anyOf` list for the response status `200`
- POST /api/v1/c/{guild_id}/tasks/ removed `#/components/schemas/TaskRecurrence-Input` from the `recurrence` request property `anyOf` list
- POST /api/v1/c/{guild_id}/tasks/ added `subschema #1` to the `recurrence` response property `anyOf` list for the response status `201`
- POST /api/v1/c/{guild_id}/tasks/reorder added `subschema #1` to the `items/recurrence` response property `anyOf` list for the response status `200`
- GET /api/v1/c/{guild_id}/tasks/{task_id} added `subschema #1` to the `recurrence` response property `anyOf` list for the response status `200`
- PATCH /api/v1/c/{guild_id}/tasks/{task_id} removed `#/components/schemas/TaskRecurrence-Input` from the `recurrence` request property `anyOf` list
- PATCH /api/v1/c/{guild_id}/tasks/{task_id} added `subschema #1` to the `recurrence` response property `anyOf` list for the response status `200`
- POST /api/v1/c/{guild_id}/tasks/{task_id}/duplicate added `subschema #1` to the `recurrence` response property `anyOf` list for the response status `201`
- POST /api/v1/c/{guild_id}/tasks/{task_id}/move added `subschema #1` to the `recurrence` response property `anyOf` list for the response status `200`
- PUT /api/v1/c/{guild_id}/tasks/{task_id}/properties added `subschema #1` to the `recurrence` response property `anyOf` list for the response status `200`
- PUT /api/v1/c/{guild_id}/tasks/{task_id}/tags api path removed without deprecation
- GET /api/v1/me/calendar-entries added `subschema #1` to the `events/items/recurrence` response property `anyOf` list for the response status `200`
- GET /api/v1/me/calendar-entries added `subschema #1` to the `tasks/items/recurrence` response property `anyOf` list for the response status `200`
- GET /api/v1/me/calendar-events added `subschema #1` to the `items/items/recurrence` response property `anyOf` list for the response status `200`
- GET /api/v1/me/tasks added `subschema #1` to the `items/items/recurrence` response property `anyOf` list for the response status `200`
- GET /api/v1/me/tasks/created added `subschema #1` to the `items/items/recurrence` response property `anyOf` list for the response status `200`
- GET /api/v1/notifications/ response property `unread_count` list-of-types was widened by adding types `null` to media type `application/json` of response `200`
- GET /api/v1/users/decoration-art api path removed without deprecation
