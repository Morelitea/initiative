import pytest
from pydantic import ValidationError

from app.schemas.platform.settings import PushSettingsUpdate


def test_push_settings_take_a_service_account_object():
    payload = PushSettingsUpdate(service_account_json='{"type": "service_account"}')
    assert payload.service_account_json == '{"type": "service_account"}'


@pytest.mark.parametrize("value", [None, ""])
def test_push_settings_clear_the_service_account(value):
    payload = PushSettingsUpdate(service_account_json=value)
    assert payload.service_account_json == value


@pytest.mark.parametrize("value", ["not json", '["a list"]', '"a string"'])
def test_push_settings_refuse_anything_but_a_json_object(value):
    with pytest.raises(ValidationError):
        PushSettingsUpdate(service_account_json=value)
