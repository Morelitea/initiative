"""A profile pack carries its own artwork.

The owner uploads a picture to the marketplace and names it in a pack's
listing file; the pack's contents, the library of whoever installs it, and the
lookup a profile uses to draw somebody else's decorations all answer with it.
"""

from app.testing import png_bytes

UID = "ART0PACK000001"


async def _publish_pack(client, owner) -> str:
    uploaded = await client.post(
        "/api/v1/marketplace/local/media",
        files={"file": ("star.png", png_bytes(6, 6), "image/png")},
        headers=owner.headers,
    )
    assert uploaded.status_code == 201, uploaded.text
    path = uploaded.json()["path"]
    published = await client.post(
        "/api/v1/marketplace/local/upload",
        json={
            "manifest": {
                "uid": UID,
                "public_id": "ours.stickers",
                "kind": "profile_pack",
                "name": "Stickers",
                "publisher": "Our deployment",
                "description": "Stickers.",
                "version": "1.0.0",
                "definition": {
                    "schema_version": 1,
                    "kind": "profile_pack",
                    "decorations": [
                        {
                            "id": "ours.star",
                            "slot": "trophy",
                            "name": "Star",
                            "image": path,
                        }
                    ],
                },
            }
        },
        headers=owner.headers,
    )
    assert published.status_code == 201, published.text
    return path


class TestAPackCarriesItsArt:
    async def test_the_shelf_shows_each_decorations_picture(self, client, acting_user):
        owner = await acting_user("owner")
        path = await _publish_pack(client, owner)
        member = await acting_user("member")

        shelf = await client.get(
            "/api/v1/users/me/decoration-packs", headers=member.headers
        )

        assert shelf.status_code == 200, shelf.text
        [pack] = [item for item in shelf.json()["items"] if item["uid"] == UID]
        assert pack["contents"][0]["image_url"] == path

    async def test_the_library_of_whoever_installs_it_draws_it(
        self, client, acting_user
    ):
        owner = await acting_user("owner")
        path = await _publish_pack(client, owner)
        member = await acting_user("member")
        installed = await client.post(
            f"/api/v1/users/me/decoration-packs/{UID}", headers=member.headers
        )
        assert installed.status_code == 200, installed.text

        library = await client.get(
            "/api/v1/users/me/decorations", headers=member.headers
        )

        [star] = [item for item in library.json()["items"] if item["id"] == "ours.star"]
        assert star["image_url"] == path

    async def test_anyone_can_look_up_the_art_a_profile_names(
        self, client, acting_user
    ):
        owner = await acting_user("owner")
        path = await _publish_pack(client, owner)
        viewer = await acting_user("member")

        response = await client.get(
            "/api/v1/users/decoration-art",
            params=[("ids", "ours.star"), ("ids", "nobody.has.this")],
            headers=viewer.headers,
        )

        assert response.status_code == 200, response.text
        assert response.json()["art"] == {"ours.star": path}
