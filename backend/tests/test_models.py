"""Document base and repository.

The repository tests need a real MongoDB. They are skipped unless one is reachable at
``TEST_MONGODB_URL`` (default ``mongodb://127.0.0.1:27017``), e.g.

    docker run --rm -d -p 27017:27017 --name mh-mongo mongo:8
    TEST_MONGODB_URL=mongodb://127.0.0.1:27017 uv run pytest tests/test_models.py
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator

import pytest
from bson import ObjectId
from pydantic import ValidationError
from pymongo import AsyncMongoClient
from pymongo.errors import PyMongoError

from app.core.database import MongoDatabase
from app.models import MongoDocument, MongoRepository

TEST_MONGODB_URL = os.environ.get("TEST_MONGODB_URL", "mongodb://127.0.0.1:27017")
TEST_DATABASE_NAME = "menuhero_test"


class Recipe(MongoDocument):
    """Example document used only by these tests (the app defines no collections yet)."""

    name: str
    servings: int = 1


class RecipeRepository(MongoRepository[Recipe]):
    collection_name = "recipes"
    document_type = Recipe


# --------------------------------------------------------------------------- schema-only


def test_object_id_accepts_string_and_instance() -> None:
    oid = ObjectId()
    assert Recipe(_id=oid, name="a").id == oid
    assert Recipe(_id=str(oid), name="a").id == oid
    assert Recipe(name="a").id is None


def test_object_id_rejects_garbage() -> None:
    with pytest.raises(ValidationError):
        Recipe(_id="not-an-object-id", name="a")


def test_id_alias_and_json_round_trip() -> None:
    oid = ObjectId()
    recipe = Recipe(id=oid, name="soup", servings=2)  # populate_by_name
    assert recipe.model_dump(by_alias=True)["_id"] == oid
    assert recipe.model_dump_json() == f'{{"id":"{oid}","name":"soup","servings":2}}'


def test_json_schema_renders_id_as_string() -> None:
    """FastAPI must be able to build OpenAPI from any document model."""
    schema = Recipe.model_json_schema()
    assert schema["properties"]["_id"]["anyOf"][0] == {"type": "string"}


def test_to_mongo_drops_unset_id() -> None:
    assert "_id" not in Recipe(name="soup").to_mongo()
    oid = ObjectId()
    assert Recipe(_id=oid, name="soup").to_mongo()["_id"] == oid


def test_from_mongo_ignores_unknown_fields() -> None:
    oid = ObjectId()
    recipe = Recipe.from_mongo({"_id": oid, "name": "soup", "servings": 3, "legacy": "x"})
    assert (recipe.id, recipe.name, recipe.servings) == (oid, "soup", 3)


# -------------------------------------------------------------- against a real MongoDB


@pytest.fixture
async def database() -> AsyncIterator[MongoDatabase]:
    client: AsyncMongoClient[dict[str, object]] = AsyncMongoClient(
        TEST_MONGODB_URL, serverSelectionTimeoutMS=1_000
    )
    try:
        await client.admin.command("ping")
    except PyMongoError as exc:  # pragma: no cover - depends on the environment
        await client.aclose()
        pytest.skip(f"no MongoDB at {TEST_MONGODB_URL}: {type(exc).__name__}")
    try:
        yield client[TEST_DATABASE_NAME]
    finally:
        await client.drop_database(TEST_DATABASE_NAME)
        await client.aclose()


async def test_repository_round_trip(database: MongoDatabase) -> None:
    repository = RecipeRepository(database)
    await repository.ensure_indexes()

    inserted_id = await repository.insert(Recipe(name="ramen", servings=2))
    assert isinstance(inserted_id, ObjectId)

    stored = await repository.get(inserted_id)
    assert stored is not None
    assert (stored.id, stored.name, stored.servings) == (inserted_id, "ramen", 2)
    assert await repository.get(str(inserted_id)) == stored
    assert await repository.get(ObjectId()) is None


async def test_repository_find_count_delete(database: MongoDatabase) -> None:
    repository = RecipeRepository(database)
    for name, servings in [("a", 1), ("b", 2), ("c", 3)]:
        await repository.insert(Recipe(name=name, servings=servings))

    assert await repository.count() == 3
    assert await repository.count({"servings": {"$gte": 2}}) == 2

    descending = await repository.find(sort=[("servings", -1)])
    assert [recipe.name for recipe in descending] == ["c", "b", "a"]
    # Always sort when order is asserted: MongoDB does not promise insertion order.
    assert [r.name for r in await repository.find(limit=2, sort=[("servings", 1)])] == ["a", "b"]
    assert [recipe.name for recipe in await repository.find({"name": "b"})] == ["b"]

    target = descending[0]
    assert target.id is not None
    assert await repository.delete(target.id) is True
    assert await repository.delete(target.id) is False
    assert await repository.count() == 2
