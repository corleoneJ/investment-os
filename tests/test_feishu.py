from unittest.mock import Mock

from src.feishu import FeishuClient


def test_missing_webhook_does_not_send_or_crash() -> None:
    client = FeishuClient(webhook="")
    client.session.post = Mock()
    assert client.send("测试") is False
    client.session.post.assert_not_called()


def test_webhook_sends_expected_text_payload() -> None:
    client = FeishuClient(webhook="https://example.test/webhook")
    response = Mock()
    response.raise_for_status.return_value = None
    response.json.return_value = {"code": 0}
    client.session.post = Mock(return_value=response)
    assert client.send("中文测试") is True
    _, kwargs = client.session.post.call_args
    assert kwargs["json"] == {"msg_type": "text", "content": {"text": "中文测试"}}
    assert kwargs["timeout"] == 8.0
