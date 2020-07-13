from datasette.app import Datasette
from datasette_auth_passwords import utils
import pytest
import httpx

TEST_METADATA = {
    "plugins": {
        "datasette-auth-passwords": {
            "accounts": {
                "user1": {
                    # Password is "password!"
                    "password_hash": "pbkdf2_sha256$260000$a9bb87a3e9d968847a36c50cf1a4ac3d$UO1DUqulWhRLj8UZrnViiu6KaKn0C5M9IZKWB4R9JX4=",
                    "actor": {"id": "user1"},
                }
            }
        }
    }
}


@pytest.mark.asyncio
async def test_plugin_is_installed():
    app = Datasette([], memory=True).app()
    async with httpx.AsyncClient(app=app) as client:
        response = await client.get("http://localhost/-/plugins.json")
        assert 200 == response.status_code
        installed_plugins = {p["name"] for p in response.json()}
        assert "datasette-auth-passwords" in installed_plugins


def test_utils_hash_password():
    hashed_password = utils.hash_password("hello")
    assert hashed_password.count("$") == 3
    assert hashed_password.startswith("pbkdf2_sha256$")
    # Running same again should return a different password
    hashed_password2 = utils.hash_password("hello")
    assert hashed_password2 != hashed_password


def test_verify_password():
    hashed_password = utils.hash_password("hello")
    assert utils.verify_password("hello", hashed_password)
    assert not utils.verify_password("hello2", hashed_password)
    # Should fail if hashed_password is invalid:
    assert not utils.verify_password("hello3", None)
    assert not utils.verify_password("hello3", "Only$two$dollars")


@pytest.mark.asyncio
async def test_password_tool():
    app = Datasette([], memory=True).app()
    async with httpx.AsyncClient(app=app) as client:
        response1 = await client.get("http://localhost/-/password-tool")
        csrftoken = response1.cookies["ds_csrftoken"]
        response2 = await client.post(
            "http://localhost/-/password-tool",
            data={"csrftoken": csrftoken, "password": "password!"},
        )
        html = response2.text
        assert ">pbkdf2_sha256$" in html
        password_hash = (
            "pbkdf2_sha256$" + html.split(">pbkdf2_sha256$")[1].split("<")[0]
        )
        assert utils.verify_password("password!", password_hash)


@pytest.mark.asyncio
async def test_login_warning_no_accounts():
    app = Datasette([], memory=True).app()
    message = "This instance does not have any configured accounts"
    async with httpx.AsyncClient(app=app) as client:
        response = await client.get("http://localhost/-/login")
        assert message in response.text
    app2 = Datasette([], memory=True, metadata=TEST_METADATA).app()
    async with httpx.AsyncClient(app=app2) as client2:
        response2 = await client2.get("http://localhost/-/login")
        assert message not in response2.text


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "username,password,should_login",
    [
        ("user1", "password!", True),
        ("user1", "password", False),
        ("user1", "", False),
        ("user2", "password!", False),
    ],
)
async def test_login(username, password, should_login):
    ds = Datasette([], memory=True, metadata=TEST_METADATA)
    async with httpx.AsyncClient(app=ds.app()) as client:
        # Get csrftoken
        csrftoken = (await client.get("http://localhost/-/login")).cookies[
            "ds_csrftoken"
        ]
        response = await client.post(
            "http://localhost/-/login",
            data={"csrftoken": csrftoken, "username": username, "password": password},
            allow_redirects=False,
        )
        if should_login:
            assert response.status_code == 302
            ds_actor = response.cookies["ds_actor"]
            assert ds.unsign(ds_actor, "actor") == {"a": {"id": "user1"}}
        else:
            assert response.status_code == 200
            assert "Invalid username or password" in response.text
