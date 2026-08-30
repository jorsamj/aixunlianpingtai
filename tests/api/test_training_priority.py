import pytest
from fastapi import HTTPException
from pydantic import ValidationError


@pytest.mark.parametrize("value", [1, 50, 999])
def test_training_priority_accepts_integer_range(value):
    import app as app_module

    payload = app_module.TrainReq(queue_priority=value)
    app_module.validate_train_request(payload)

    assert payload.queue_priority == value


@pytest.mark.parametrize("value", [0, -1, 1000])
def test_training_priority_rejects_out_of_range_integer(value):
    import app as app_module

    payload = app_module.TrainReq(queue_priority=value)
    with pytest.raises(HTTPException, match="1~999"):
        app_module.validate_train_request(payload)


@pytest.mark.parametrize("value", [True, 1.5, "1", ""])
def test_training_priority_rejects_non_integer_input(value):
    import app as app_module

    with pytest.raises(ValidationError):
        app_module.TrainReq(queue_priority=value)
