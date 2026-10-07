"""API responses shaped like Mailpit's, for unit tests."""

from typing import Any

SUMMARY: dict[str, Any] = {
    "ID": "Aa1Bb2Cc3Dd4Ee5Ff6Gg7H",
    "MessageID": "order-1001@shop.example.test",
    "Read": False,
    "From": {"Name": "Shop", "Address": "orders@shop.example.test"},
    "To": [{"Name": "Ivan Petrov", "Address": "ivan@example.test"}],
    "Cc": [{"Name": "", "Address": "accounts@example.test"}],
    "Bcc": [],
    "ReplyTo": [{"Name": "Support", "Address": "support@shop.example.test"}],
    "Subject": "Поръчка №1001",
    "Created": "2026-10-07T11:22:33.123456789Z",
    "Username": "shop",
    "Tags": ["orders"],
    "Size": 4821,
    "Attachments": 1,
    "Snippet": "Thank you for your order.",
}

MESSAGE: dict[str, Any] = {
    "ID": "Aa1Bb2Cc3Dd4Ee5Ff6Gg7H",
    "MessageID": "order-1001@shop.example.test",
    "From": {"Name": "Shop", "Address": "orders@shop.example.test"},
    "To": [{"Name": "Ivan Petrov", "Address": "ivan@example.test"}],
    "Cc": [{"Name": "", "Address": "accounts@example.test"}],
    "Bcc": None,
    "ReplyTo": [{"Name": "Support", "Address": "support@shop.example.test"}],
    "ReturnPath": "bounces@shop.example.test",
    "Subject": "Поръчка №1001",
    "ListUnsubscribe": {
        "Header": "<mailto:unsubscribe@shop.example.test>, <https://shop.example.test/u/1>",
        "HeaderPost": "List-Unsubscribe=One-Click",
        "Links": ["unsubscribe@shop.example.test", "https://shop.example.test/u/1"],
        "Errors": "",
    },
    "Date": "2026-10-07T14:22:33+03:00",
    "Tags": ["orders"],
    "Username": "shop",
    "Text": "Thank you for your order.\nTrack it: https://shop.example.test/orders/1001",
    "HTML": '<p>Thank you for your order.</p><a href="https://shop.example.test/orders/1001">Track</a>',
    "Size": 4821,
    "Inline": [],
    "Attachments": [
        {
            "PartID": "2",
            "FileName": "invoice-1001.pdf",
            "ContentType": "application/pdf",
            "ContentID": "",
            "Size": 1234,
            "Checksums": {"MD5": "0123456789abcdef0123456789abcdef"},
        }
    ],
}

MESSAGE_LIST: dict[str, Any] = {
    "total": 12,
    "unread": 3,
    "messages_count": 1,
    "messages_unread": 1,
    "start": 0,
    "tags": ["orders"],
    "messages": [SUMMARY],
}

INFO: dict[str, Any] = {
    "Version": "v1.31.4",
    "LatestVersion": "v1.31.4",
    "Database": "/tmp/mailpit.db",
    "DatabaseSize": 98304,
    "Messages": 12,
    "Unread": 3,
    "Tags": {"orders": 1},
    "RuntimeStats": {"Uptime": 60},
}

# What an older Mailpit (v1.22) sends: no Username, and an unknown future field must not break.
OLD_SUMMARY: dict[str, Any] = {
    key: value for key, value in SUMMARY.items() if key not in {"Username", "ReplyTo", "Snippet"}
} | {"SomeFutureField": {"nested": True}}
