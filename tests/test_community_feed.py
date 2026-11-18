"""The website has one chronological feed, scoped to each driver's circle."""

from datetime import date, datetime, timedelta
from html.parser import HTMLParser
import unittest

from werkzeug.security import generate_password_hash

from racetrack.models import db, DriverConnection, SocialComment, SocialPost, User, UserBlock
from test_browser_privacy import make_privacy_test_app, PageMarkup


class FeedMarkup(HTMLParser):
    def __init__(self, body):
        super().__init__()
        self.post_ids = []
        self.older_url = None
        self.feed(body)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "article" and "data-post-id" in attrs:
            self.post_ids.append(int(attrs["data-post-id"]))
        if tag == "a" and "before=" in attrs.get("href", ""):
            self.older_url = attrs["href"]


class CommunityFeedTest(unittest.TestCase):
    def setUp(self):
        self.app = make_privacy_test_app()
        self.client = self.app.test_client()
        self.when = datetime.utcnow() - timedelta(days=1)
        with self.app.app_context():
            self.password_hash = generate_password_hash("FeedTestPassword123!")
            self.me_id = self.driver("me").id
            self.friend_id = self.driver("friend").id
            self.stranger_id = self.driver("stranger").id
            db.session.add(DriverConnection(
                user_one_id=self.me_id, user_two_id=self.friend_id,
                requested_by_user_id=self.me_id, status="accepted",
            ))
            db.session.commit()
        self.login()

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.drop_all()

    def driver(self, name, **extra):
        user = User(
            first_name=name.title(), last_name="Driver", username=name,
            email=f"{name}@example.com", phone="555-0100", date_of_birth=date(1990, 1, 1),
            street="1 Test St", city="Austin", state="TX", postal_code="78701",
            password_hash=self.password_hash, **extra,
        )
        db.session.add(user)
        db.session.flush()
        return user

    def post_record(self, user_id, post_type="driver_update", minutes=0, body="A track update"):
        post = SocialPost(user_id=user_id, post_type=post_type, title="Shared an update",
                          body=body, created_at=self.when + timedelta(minutes=minutes))
        db.session.add(post)
        db.session.flush()
        return post.id

    def get(self, path="/user/community"):
        return self.client.get(path, base_url="https://localhost")

    def submit(self, path, data):
        csrf = PageMarkup(self.get("/login").get_data(as_text=True)).csrf_token
        if not csrf:
            csrf = PageMarkup(self.get().get_data(as_text=True)).csrf_token
        return self.client.post(path, base_url="https://localhost", data={**data, "csrf_token": csrf},
                                headers={"Referer": "https://localhost/user/community"})

    def login(self):
        response = self.submit("/login", {"email": "me@example.com", "password": "FeedTestPassword123!"})
        self.assertEqual(response.status_code, 302)

    def markup(self, path="/user/community"):
        response = self.get(path)
        self.assertEqual(response.status_code, 200)
        return FeedMarkup(response.get_data(as_text=True))

    def test_all_post_types_and_own_posts_share_newest_first_timeline(self):
        with self.app.app_context():
            ids = [
                self.post_record(self.me_id, "driver_update", 1),
                self.post_record(self.friend_id, "event_signup", 2),
                self.post_record(self.me_id, "car_spotlight", 3),
                self.post_record(self.friend_id, "run_share", 3),
            ]
            db.session.commit()
        # Equal timestamps sort by ID; old bookmarks also show the unified feed.
        for suffix in ("", "?view=mine", "?view=track", "?view=builds"):
            with self.subTest(view=suffix):
                self.assertEqual(self.markup("/user/community" + suffix).post_ids, list(reversed(ids)))
        self.assertNotIn(b'class="community-tabs"', self.get().data)

    def test_new_post_appears_first_then_moves_down_when_another_driver_posts(self):
        with self.app.app_context():
            old_id = self.post_record(self.friend_id)
            db.session.commit()
        response = self.submit("/user/community/posts", {"body": "Ready for the weekend!"})
        self.assertEqual(response.status_code, 302)
        own_id = self.markup().post_ids[0]
        self.assertEqual(response.location, f"/user/community#post-{own_id}")
        self.assertEqual(self.markup().post_ids, [own_id, old_id])
        with self.app.app_context():
            own_post = db.session.get(SocialPost, own_id)
            later_post = SocialPost(user_id=self.friend_id, post_type="driver_update", title="Shared an update",
                                    body="See you there!", created_at=own_post.created_at + timedelta(seconds=1))
            db.session.add(later_post)
            db.session.commit()
            later_id = later_post.id
        self.assertEqual(self.markup().post_ids, [later_id, own_id, old_id])

    def test_older_posts_remain_accessible_and_new_arrivals_do_not_duplicate_pages(self):
        with self.app.app_context():
            ids = [self.post_record(self.me_id if index % 2 else self.friend_id) for index in range(55)]
            db.session.commit()
        first = self.markup()
        self.assertEqual(len(first.post_ids), 20)
        with self.app.app_context():
            new_id = self.post_record(self.friend_id, minutes=1)
            db.session.commit()
        seen = first.post_ids[:]
        next_url = first.older_url
        while next_url:
            page = self.markup(next_url)
            seen.extend(page.post_ids)
            next_url = page.older_url
        self.assertEqual(seen, list(reversed(ids)))
        self.assertEqual(len(set(seen)), 55)
        self.assertEqual(self.markup().post_ids[0], new_id)

    def test_private_pending_blocked_deleted_and_suspended_authors_are_hidden(self):
        with self.app.app_context():
            visible = self.post_record(self.friend_id)
            self.post_record(self.stranger_id)
            for name, status in (("pending", "pending"), ("blocked", "accepted"),
                                  ("blocksme", "accepted"), ("deleted", "accepted"), ("suspended", "accepted")):
                user = self.driver(name)
                db.session.add(DriverConnection(user_one_id=self.me_id, user_two_id=user.id,
                                                requested_by_user_id=self.me_id, status=status))
                self.post_record(user.id)
                if name == "blocked":
                    db.session.add(UserBlock(blocker_user_id=self.me_id, blocked_user_id=user.id))
                elif name == "blocksme":
                    db.session.add(UserBlock(blocker_user_id=user.id, blocked_user_id=self.me_id))
                elif name == "deleted":
                    user.deleted_at = datetime.utcnow()
                elif name == "suspended":
                    user.community_suspended_at = datetime.utcnow()
                db.session.add(SocialComment(post_id=visible, user_id=user.id, body=f"hidden-comment-{name}"))
            db.session.add(SocialComment(post_id=visible, user_id=self.me_id, body="visible-comment"))
            db.session.commit()
        response = self.get()
        self.assertEqual(FeedMarkup(response.get_data(as_text=True)).post_ids, [visible])
        self.assertIn(b"visible-comment", response.data)
        self.assertNotIn(b"hidden-comment-", response.data)

    def test_new_driver_can_see_their_first_post_without_connections(self):
        with self.app.app_context():
            DriverConnection.query.delete()
            db.session.commit()
        self.assertIn(b"Start the conversation", self.get().data)
        response = self.submit("/user/community/posts", {"body": "First track day booked!"})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(len(self.markup().post_ids), 1)

    def test_comments_cannot_cross_connection_or_block_boundaries(self):
        with self.app.app_context():
            friend_post = self.post_record(self.friend_id)
            stranger_post = self.post_record(self.stranger_id)
            db.session.commit()
        self.assertEqual(self.submit(f"/user/community/posts/{friend_post}/comment", {"body": "See you there"}).status_code, 302)
        self.assertEqual(self.submit(f"/user/community/posts/{stranger_post}/comment", {"body": "Not allowed"}).status_code, 404)
        with self.app.app_context():
            db.session.add(UserBlock(blocker_user_id=self.friend_id, blocked_user_id=self.me_id))
            db.session.commit()
        self.assertEqual(self.submit(f"/user/community/posts/{friend_post}/comment", {"body": "Not allowed"}).status_code, 404)
        with self.app.app_context():
            self.assertEqual(SocialComment.query.count(), 1)

    def test_cursor_cannot_reveal_a_private_post(self):
        with self.app.app_context():
            hidden_id = self.post_record(self.stranger_id)
            db.session.commit()
        response = self.get(f"/user/community?before={hidden_id}")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.location, "/user/community")

    def test_posting_requires_csrf_and_nonempty_content(self):
        self.assertEqual(self.client.post("/user/community/posts", base_url="https://localhost", data={"body": "Missing token"}).status_code, 400)
        self.assertEqual(self.submit("/user/community/posts", {"body": "   "}).status_code, 302)
        with self.app.app_context():
            self.assertEqual(SocialPost.query.count(), 0)


if __name__ == "__main__":
    unittest.main()
