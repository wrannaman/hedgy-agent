import unittest

from shared.accounts import account_by_suffix


class Response:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


class Client:
    def __init__(self, accounts):
        self.accounts = accounts

    def get_account_numbers(self):
        return Response(self.accounts)


class AccountSelectionTests(unittest.TestCase):
    def test_selects_account_by_suffix_not_position(self):
        client = Client([
            {"accountNumber": "123456101", "hashValue": "main"},
            {"accountNumber": "999888201", "hashValue": "401k"},
        ])

        self.assertEqual(account_by_suffix(client, "201")["hashValue"], "401k")

    def test_missing_suffix_raises(self):
        with self.assertRaises(ValueError):
            account_by_suffix(Client([]), "201")

    def test_duplicate_suffix_raises(self):
        client = Client([
            {"accountNumber": "111201", "hashValue": "a"},
            {"accountNumber": "222201", "hashValue": "b"},
        ])

        with self.assertRaises(ValueError):
            account_by_suffix(client, "201")


if __name__ == "__main__":
    unittest.main()
