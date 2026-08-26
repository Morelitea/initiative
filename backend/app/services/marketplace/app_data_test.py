"""The bounds around one upstream call, and the parameter contract.

Everything here is driven by an injected `httpx.MockTransport`, so nothing
touches the network. What it pins is the part of the proxy that has to hold when
an app misbehaves rather than merely being absent: a response that never ends, a
response far too large, a response that is not JSON, and a response that is JSON
but not data. All four are the *app* failing, and all four have to come back as
one named code — a dashboard tile, not a server fault.

The parameter tests are the other half of the same idea. A source's
``params_schema`` is the whole of what a widget may vary, so anything outside it
is refused here rather than forwarded for the app to puzzle over.
"""

import json

import httpx
import pytest

from app.core.messages import AppDataMessages
from app.models.platform.app_service_registration import AppServiceRegistration
from app.services.marketplace import app_data as service

pytestmark = pytest.mark.unit

URL = "http://127.0.0.1:9100/v1/endpoints"

ORDERS = "app.acme.shop.orders"

SOURCE = {
    "id": ORDERS,
    "direction": "read",
    "visibility": "member",
    "cache_ttl_seconds": 60,
    "params": [
        {"key": "range", "type": "select", "options": ["7d", "30d"], "label": {}},
        {"key": "limit", "type": "int", "label": {}},
        {"key": "team", "type": "string", "label": {}},
        {"key": "detailed", "type": "bool", "label": {}},
        {"key": "callback", "type": "url", "label": {}},
    ],
}


async def _read(handler) -> list:
    return await service._read_rows(
        httpx.Request("POST", URL), transport=httpx.MockTransport(handler)
    )


# --- what an app may answer with --------------------------------------------


def _answer(rows) -> dict:
    """What an app answers a call with: what it ran, whose credential ran it,
    and the result. The rows are one level in."""
    return {"endpoint": ORDERS, "actor": "member", "result": {"rows": rows}}


class TestUpstreamBounds:
    async def test_rows_come_back_verbatim(self):
        payload = [{"id": 1, "nested": {"deep": [1, 2]}}, {"id": 2}]
        rows = await _read(lambda request: httpx.Response(200, json=_answer(payload)))
        assert rows == payload

    async def test_an_answer_without_a_result_is_the_app_being_unavailable(self):
        # From a dashboard's side "this app is not answering" is true whether
        # the service is down or talking a shape this build does not accept.
        with pytest.raises(service.AppDataError) as excinfo:
            await _read(lambda request: httpx.Response(200, json={"rows": [{"id": 1}]}))
        assert excinfo.value.code == AppDataMessages.SERVICE_UNAVAILABLE

    async def test_a_response_past_the_ceiling_is_abandoned(self):
        oversized = "x" * (service.MAX_RESPONSE_BYTES + 1024)
        with pytest.raises(service.AppDataError) as excinfo:
            await _read(lambda request: httpx.Response(200, json=_answer([oversized])))
        assert excinfo.value.code == AppDataMessages.RESPONSE_TOO_LARGE
        assert excinfo.value.status_code == 502

    async def test_a_response_that_never_arrives_is_the_app_being_unavailable(self):
        def _stall(request: httpx.Request) -> httpx.Response:
            raise httpx.ReadTimeout("timed out", request=request)

        with pytest.raises(service.AppDataError) as excinfo:
            await _read(_stall)
        assert excinfo.value.code == AppDataMessages.SERVICE_UNAVAILABLE
        assert excinfo.value.status_code == 502

    async def test_a_refused_connection_is_the_app_being_unavailable(self):
        def _refuse(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("refused", request=request)

        with pytest.raises(service.AppDataError) as excinfo:
            await _read(_refuse)
        assert excinfo.value.code == AppDataMessages.SERVICE_UNAVAILABLE

    @pytest.mark.parametrize("status", [400, 401, 404, 500, 503])
    async def test_an_error_status_is_not_passed_through_as_data(self, status):
        with pytest.raises(service.AppDataError) as excinfo:
            await _read(lambda request: httpx.Response(status, json={"rows": []}))
        assert excinfo.value.code == AppDataMessages.SERVICE_UNAVAILABLE

    async def test_a_body_that_is_not_json_is_refused(self):
        with pytest.raises(service.AppDataError) as excinfo:
            await _read(
                lambda request: httpx.Response(
                    200,
                    text="<html>hello</html>",
                    headers={"content-type": "text/html"},
                )
            )
        assert excinfo.value.code == AppDataMessages.SERVICE_UNAVAILABLE

    @pytest.mark.parametrize(
        "body", [{"data": []}, {"rows": {"a": 1}}, [1, 2, 3], "rows", 7]
    )
    async def test_json_that_is_not_a_data_response_is_refused(self, body):
        with pytest.raises(service.AppDataError) as excinfo:
            await _read(lambda request: httpx.Response(200, json=body))
        assert excinfo.value.code == AppDataMessages.SERVICE_UNAVAILABLE

    async def test_the_timeout_is_the_documented_budget(self):
        """A dashboard is a display surface: a source that cannot answer in five
        seconds is not going to render usefully."""
        assert service.REQUEST_TIMEOUT_SECONDS == 5.0
        assert service.MAX_RESPONSE_BYTES == 1024 * 1024


# --- parameters --------------------------------------------------------------


class TestParams:
    def test_no_parameters_is_an_empty_canonical_form(self):
        for raw in (None, "", "   ", "{}"):
            values, canonical = service.validate_params(SOURCE, raw)
            assert values == {}
            assert canonical == "{}"

    def test_declared_values_are_rendered_for_the_wire(self):
        values, _ = service.validate_params(
            SOURCE,
            json.dumps(
                {
                    "range": "30d",
                    "limit": 5,
                    "team": " platform ",
                    "detailed": True,
                    "callback": "https://example.test/hook",
                }
            ),
        )
        assert values == {
            "range": "30d",
            "limit": "5",
            "team": "platform",
            "detailed": "true",
            "callback": "https://example.test/hook",
        }

    def test_the_canonical_form_is_order_independent(self):
        _, first = service.validate_params(
            SOURCE, json.dumps({"range": "7d", "limit": 1})
        )
        _, second = service.validate_params(
            SOURCE, json.dumps({"limit": 1, "range": "7d"})
        )
        assert first == second

    @pytest.mark.parametrize(
        "raw",
        [
            '{"unknown": "x"}',
            '{"range": "90d"}',
            '{"range": 7}',
            '{"limit": "5"}',
            '{"limit": true}',
            '{"detailed": "yes"}',
            '{"callback": "javascript:alert(1)"}',
            '{"callback": "ftp://example.test"}',
            '{"team": ""}',
            "[]",
            "null",
            "not json",
        ],
    )
    def test_anything_outside_the_schema_is_refused(self, raw):
        with pytest.raises(service.AppDataError) as excinfo:
            service.validate_params(SOURCE, raw)
        assert excinfo.value.code == AppDataMessages.INVALID_PARAMS
        assert excinfo.value.status_code == 400

    def test_a_required_parameter_left_out_is_refused(self):
        source = {
            **SOURCE,
            "params": [
                {"key": "shop", "type": "string", "required": True, "label": {}}
            ],
        }
        with pytest.raises(service.AppDataError):
            service.validate_params(source, None)
        values, _ = service.validate_params(source, '{"shop": "acme"}')
        assert values == {"shop": "acme"}

    def test_an_oversized_parameter_object_is_refused_before_parsing(self):
        raw = json.dumps({"team": "x" * (service.MAX_PARAMS_BYTES + 10)})
        with pytest.raises(service.AppDataError) as excinfo:
            service.validate_params(SOURCE, raw)
        assert excinfo.value.code == AppDataMessages.INVALID_PARAMS


# --- reading the pinned definition -------------------------------------------


class TestDefinitionReading:
    def test_a_read_is_found_on_the_pinned_definition(self):
        definition = {"app_kind": "service", "endpoints": [SOURCE]}
        assert service.find_read_endpoint(definition, ORDERS) == SOURCE
        assert service.find_read_endpoint(definition, "app.acme.shop.other") is None

    def test_only_a_read_is_reachable_from_here(self):
        """A write and an emission are both real endpoints and neither belongs
        on the fetch path: rendering a dashboard must not be a way to make an
        app act."""
        for direction in ("write", "emit"):
            definition = {
                "app_kind": "service",
                "endpoints": [{**SOURCE, "direction": direction}],
            }
            assert service.find_read_endpoint(definition, ORDERS) is None

    def test_an_app_is_called_over_the_wire_surface(self):
        """A registration may carry two addresses. This one is Initiative's own
        server calling the app, so it uses the address meant for that — the
        browser address is for what a browser opens."""
        registration = AppServiceRegistration(
            public_id="acme.shop",
            base_url="http://acme-shop:8200",
            embed_origin="https://shop.example.com",
        )

        assert service._endpoints_url(registration) == (
            "http://acme-shop:8200/v1/endpoints"
        )

    def test_only_a_service_app_has_a_backing_service(self):
        assert (
            service.service_public_id(
                {"app_kind": "service", "service": {"public_id": "acme.shop"}}
            )
            == "acme.shop"
        )
        assert service.service_public_id({"app_kind": "tool_instance"}) is None
        assert service.service_public_id({"app_kind": "service"}) is None
        assert service.service_public_id(None) is None

    def test_the_deployments_ceiling_outranks_the_manifests_request(self):
        """A listing asks for freshness; it does not get to decide it."""
        assert service._effective_ttl({"cache_ttl_seconds": 60}) == 60
        assert (
            service._effective_ttl({"cache_ttl_seconds": 86_400})
            == service.MAX_CACHE_TTL_SECONDS
        )
        assert service._effective_ttl({"cache_ttl_seconds": -5}) == 0
        assert service._effective_ttl({"cache_ttl_seconds": True}) == 0
        assert service._effective_ttl({}) == 0
