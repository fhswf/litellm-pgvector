"""User and team ownership must agree across the local API routes."""

import unittest

from fastapi import HTTPException
from sqlalchemy import Column, Integer, MetaData, String, Table, create_engine, insert, select

from util import get_litellm_owner_ids, scope_to_litellm_owner


class OwnerScopeTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://")
        self.addCleanup(self.engine.dispose)
        self.records = Table(
            "records",
            MetaData(),
            Column("id", Integer, primary_key=True),
            Column("user_id", String),
            Column("team_id", String),
        )
        self.records.create(self.engine)
        with self.engine.begin() as connection:
            connection.execute(insert(self.records), [
                {"id": 1, "user_id": "alice", "team_id": None},
                {"id": 2, "user_id": "bob", "team_id": "team-a"},
                {"id": 3, "user_id": "alice", "team_id": "team-b"},
                {"id": 4, "user_id": "bob", "team_id": None},
            ])

    def visible_ids(self, info):
        statement = scope_to_litellm_owner(
            select(self.records.c.id), self.records.c, info
        )
        with self.engine.connect() as connection:
            return set(connection.execute(statement).scalars())

    def test_user_keys_share_user_stores(self):
        self.assertEqual(self.visible_ids({"info": {"user_id": "alice"}}), {1})

    def test_team_keys_see_their_team_and_own_user_stores(self):
        self.assertEqual(
            self.visible_ids({"info": {"user_id": "alice", "team_id": "team-a"}}),
            {1, 2},
        )
        self.assertEqual(self.visible_ids({"info": {"team_id": "team-a"}}), {2})

    def test_admin_can_access_all_stores(self):
        self.assertEqual(self.visible_ids({"is_admin": True}), {1, 2, 3, 4})

    def test_key_without_owner_is_rejected(self):
        with self.assertRaises(HTTPException) as raised:
            get_litellm_owner_ids({"info": {}})
        self.assertEqual(raised.exception.status_code, 403)


if __name__ == "__main__":
    unittest.main()
