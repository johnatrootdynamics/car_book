"""Native Community feed ordering, pagination, and privacy regressions."""

from datetime import date, datetime, timedelta
import unittest

from flask import Flask
from werkzeug.security import generate_password_hash

from racetrack.mobile_api import mobile_api_bp
from racetrack.models import (
    DriverConnection,
    SocialComment,
    SocialPost,
    SocialShare,
    User,
    UserBlock,
    db,
)


class MobileCommunityFeedTest(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.app.config.update(
            TESTING=True,
            SECRET_KEY="mobile-community-test",
            SQLALCHEMY_DATABASE_URI="sqlite://",
            SQLALCHEMY_TRACK_MODIFICATIONS=False,
            TRACK_TIMEZONE="UTC",
            APP_BASE_URL="https://example.test",
            S3_READ_ACCESS_KEY="",
            S3_READ_SECRET_KEY="",
        )
        db.init_app(self.app)
        self.app.register_blueprint(mobile_api_bp)
        with self.app.app_context():
            db.create_all()
            self.me_id = self.driver("me").id
            self.friend_id = self.driver("friend").id
            self.stranger_id = self.driver("stranger").id
            self.connect(self.me_id, self.friend_id)
            db.session.commit()
        self.client = self.app.test_client()
        self.token = self.login("me")

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.drop_all()

    def driver(self, username, **extra):
        user = User(
            first_name=username.title(),
            last_name="Driver",
            username=username,
            email=f"{username}@example.test",
            phone="555-0100",
            date_of_birth=date(1990, 1, 1),
            street="1 Test St",
            city="Austin",
            state="TX",
            postal_code="78701",
            password_hash=generate_password_hash("Password123!"),
            **extra,
        )
        db.session.add(user)
        db.session.flush()
        return user

    def connect(self, first_id, second_id, status="accepted"):
        db.session.add(
            DriverConnection(
                user_one_id=min(first_id, second_id),
                user_two_id=max(first_id, second_id),
                requested_by_user_id=first_id,
                status=status,
            )
        )

    def post(self, user_id, created_at, body="Track update"):
        post = SocialPost(
            user_id=user_id,
            post_type="driver_update",
            title="Shared an update",
            body=body,
            created_at=created_at,
        )
        db.session.add(post)
        db.session.flush()
        return post

    def login(self, username):
        response = self.client.post(
            "/api/v1/mobile/auth/login",
            json={
                "email": f"{username}@example.test",
                "password": "Password123!",
            },
        )
        self.assertEqual(response.status_code, 200)
        return response.get_json()["access_token"]

    def get_feed(self, cursor=None):
        path = "/api/v1/mobile/driver/community?view=all"
        if cursor:
            path += f"&cursor={cursor}"
        response = self.client.get(
            path, headers={"Authorization": f"Bearer {self.token}"}
        )
        self.assertEqual(response.status_code, 200, response.get_json())
        return response.get_json()

    def test_view_all_includes_own_posts_without_connections(self):
        when = datetime(2026, 11, 17, 12, 0)
        with self.app.app_context():
            DriverConnection.query.delete()
            first = self.post(self.me_id, when, "First")
            second = self.post(self.me_id, when, "Second")
            db.session.commit()
            expected = [second.id, first.id]

        payload = self.get_feed()
        self.assertEqual([post["id"] for post in payload["posts"]], expected)
        self.assertEqual(payload["connections"], [])
        self.assertIsNone(payload["next_cursor"])

    def test_feed_and_comments_hide_private_blocked_deleted_and_suspended_users(self):
        when = datetime(2026, 11, 17, 13, 0)
        with self.app.app_context():
            visible = self.post(self.friend_id, when)
            self.post(self.stranger_id, when + timedelta(minutes=1))
            hidden_users = []
            for username in ("blocked", "blocksme", "deleted", "suspended"):
                user = self.driver(username)
                self.connect(self.me_id, user.id)
                self.post(user.id, when + timedelta(minutes=2))
                hidden_users.append(user)
            db.session.add(UserBlock(blocker_user_id=self.me_id, blocked_user_id=hidden_users[0].id))
            db.session.add(UserBlock(blocker_user_id=hidden_users[1].id, blocked_user_id=self.me_id))
            hidden_users[2].deleted_at = datetime.utcnow()
            hidden_users[3].community_suspended_at = datetime.utcnow()
            db.session.add(SocialComment(post_id=visible.id, user_id=self.me_id, body="Visible me"))
            db.session.add(SocialComment(post_id=visible.id, user_id=self.friend_id, body="Visible friend"))
            for user in hidden_users:
                db.session.add(SocialComment(post_id=visible.id, user_id=user.id, body=f"Hidden {user.username}"))
            db.session.commit()
            visible_id = visible.id

        payload = self.get_feed()
        self.assertEqual([post["id"] for post in payload["posts"]], [visible_id])
        comments = payload["posts"][0]["comments"]
        self.assertEqual([comment["body"] for comment in comments], ["Visible me", "Visible friend"])
        self.assertEqual([row["user"]["id"] for row in payload["connections"]], [self.friend_id])

    def test_cursor_pages_posts_and_shares_without_duplicates_after_new_arrival(self):
        start = datetime(2026, 11, 1, 8, 0)
        with self.app.app_context():
            posts = [
                self.post(
                    self.me_id if index % 2 else self.friend_id,
                    start + timedelta(minutes=index // 3),
                    f"Post {index}",
                )
                for index in range(42)
            ]
            shared = SocialShare(
                post_id=posts[1].id,
                user_id=self.friend_id,
                body="Worth sharing",
                created_at=start + timedelta(minutes=7),
            )
            db.session.add(shared)
            db.session.flush()
            expected_rows = [
                (post.created_at, 1, post.id, post.id) for post in posts
            ] + [(shared.created_at, 0, shared.id, -shared.id)]
            expected_rows.sort(key=lambda row: row[:3], reverse=True)
            expected_ids = [row[3] for row in expected_rows]
            db.session.commit()

        first = self.get_feed()
        self.assertEqual(len(first["posts"]), 20)
        self.assertTrue(first["next_cursor"])

        with self.app.app_context():
            newcomer = self.post(self.friend_id, start + timedelta(days=1), "New arrival")
            db.session.commit()
            newcomer_id = newcomer.id

        seen = [post["id"] for post in first["posts"]]
        cursor = first["next_cursor"]
        while cursor:
            page = self.get_feed(cursor)
            seen.extend(post["id"] for post in page["posts"])
            cursor = page["next_cursor"]

        self.assertEqual(seen, expected_ids)
        self.assertEqual(len(seen), len(set(seen)))
        self.assertEqual(self.get_feed()["posts"][0]["id"], newcomer_id)

        invalid = self.client.get(
            "/api/v1/mobile/driver/community?cursor=not-a-valid-cursor",
            headers={"Authorization": f"Bearer {self.token}"},
        )
        self.assertEqual(invalid.status_code, 400)
        self.assertEqual(invalid.get_json()["error"], "invalid_cursor")


if __name__ == "__main__":
    unittest.main()
