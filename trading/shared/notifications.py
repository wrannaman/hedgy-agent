"""Optional Slack notifications with environment/local configuration and safe errors."""
import sys
import requests
from shared.settings import setting


def webhook():
    return setting('SLACK_TRADING_WEBHOOK').strip()


def post_message(message):
    url = webhook()
    if not url:
        return False
    try:
        response = requests.post(url, json={'text': message}, timeout=20)
        return response.ok
    except requests.RequestException:
        # A webhook URL is a credential and may appear in Requests exceptions.
        return False


if __name__ == '__main__':
    # Message on stdin; the webhook never enters curl argv or a child process log.
    raise SystemExit(0 if post_message(sys.stdin.read()) else 1)
