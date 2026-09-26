"""Building blocks for MongoDB documents and their repositories.

MongoDB has no schema to declare up front, so this module carries the two pieces every
future collection needs instead: a Pydantic-friendly ``ObjectId`` type and a small generic
repository that keeps driver calls out of the service layer.

    class Recipe(MongoDocument):
        name: str

    class RecipeRepository(MongoRepository[Recipe]):
        collection_name = "recipes"
        document_type = Recipe

No collections exist yet; nothing here connects on its own.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Annotated, Any, ClassVar, Self

from bson import ObjectId
from pydantic import BaseModel, ConfigDict, Field, GetCoreSchemaHandler, GetJsonSchemaHandler
from pydantic.json_schema import JsonSchemaValue
from pydantic_core import core_schema
from pymongo import ASCENDING, DESCENDING, ReturnDocument
from pymongo.asynchronous.collection import AsyncCollection

from app.core.database import Document, MongoDatabase

__all__ = [
    "ASCENDING",
    "DESCENDING",
    "MongoDocument",
    "MongoRepository",
    "PyObjectId",
]


class _ObjectIdAnnotation:
    """Pydantic v2 support for :class:`bson.ObjectId`: parsed from a string, dumped as one."""

    @classmethod
    def __get_pydantic_core_schema__(
        cls, source_type: Any, handler: GetCoreSchemaHandler
    ) -> core_schema.CoreSchema:
        def validate(value: str) -> ObjectId:
            if not ObjectId.is_valid(value):
                raise ValueError("not a valid ObjectId")
            return ObjectId(value)

        from_str = core_schema.chain_schema(
            [core_schema.str_schema(), core_schema.no_info_plain_validator_function(validate)]
        )
        return core_schema.json_or_python_schema(
            json_schema=from_str,
            python_schema=core_schema.union_schema(
                [core_schema.is_instance_schema(ObjectId), from_str]
            ),
            serialization=core_schema.plain_serializer_function_ser_schema(
                str, return_schema=core_schema.str_schema(), when_used="json"
            ),
        )

    @classmethod
    def __get_pydantic_json_schema__(
        cls, schema: core_schema.CoreSchema, handler: GetJsonSchemaHandler
    ) -> JsonSchemaValue:
        return handler(core_schema.str_schema())


PyObjectId = Annotated[ObjectId, _ObjectIdAnnotation]
"""``ObjectId`` in Python, a plain string in JSON and in the OpenAPI schema."""


class MongoDocument(BaseModel):
    """Base class for documents: adds the ``_id`` field and BSON conversion helpers."""

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    id: PyObjectId | None = Field(default=None, alias="_id")

    def to_mongo(self) -> Document:
        """Return the BSON body to store, dropping ``_id`` when the server should assign it."""
        data = self.model_dump(by_alias=True)
        if data.get("_id") is None:
            data.pop("_id", None)
        return data

    @classmethod
    def from_mongo(cls, raw: Mapping[str, Any]) -> Self:
        """Build a document from a raw driver result."""
        return cls.model_validate(raw)


class MongoRepository[TDocument: MongoDocument]:
    """Typed access to one collection. Subclasses set ``collection_name`` and ``document_type``."""

    collection_name: ClassVar[str]
    document_type: type[TDocument]

    def __init__(self, database: MongoDatabase) -> None:
        self._database = database

    @property
    def collection(self) -> AsyncCollection[Document]:
        """The underlying driver collection."""
        return self._database[self.collection_name]

    async def ensure_indexes(self) -> None:
        """Create the collection's indexes. Override where a collection needs them."""
        return None

    async def insert(self, document: TDocument) -> ObjectId:
        """Insert ``document`` and return the server-assigned ``_id``."""
        result = await self.collection.insert_one(document.to_mongo())
        inserted: ObjectId = result.inserted_id
        return inserted

    async def get(self, document_id: ObjectId | str) -> TDocument | None:
        """Return one document by id, or ``None`` when it does not exist."""
        raw = await self.collection.find_one({"_id": ObjectId(document_id)})
        return None if raw is None else self.document_type.from_mongo(raw)

    async def find_one(self, filter: Mapping[str, Any]) -> TDocument | None:
        """Return the first document matching ``filter``, or ``None``."""
        raw = await self.collection.find_one(dict(filter))
        return None if raw is None else self.document_type.from_mongo(raw)

    async def find(
        self,
        filter: Mapping[str, Any] | None = None,
        *,
        limit: int = 0,
        sort: Sequence[tuple[str, int]] | None = None,
    ) -> list[TDocument]:
        """Return the documents matching ``filter`` (all of them when it is omitted)."""
        cursor = self.collection.find(dict(filter or {}), limit=limit)
        if sort is not None:
            cursor = cursor.sort(list(sort))
        return [self.document_type.from_mongo(raw) async for raw in cursor]

    async def count(self, filter: Mapping[str, Any] | None = None) -> int:
        """Number of documents matching ``filter``."""
        return await self.collection.count_documents(dict(filter or {}))

    async def update_by_id(
        self, document_id: ObjectId | str, changes: Mapping[str, Any]
    ) -> TDocument | None:
        """``$set`` ``changes`` on one document and return it as stored afterwards."""
        raw = await self.collection.find_one_and_update(
            {"_id": ObjectId(document_id)},
            {"$set": dict(changes)},
            return_document=ReturnDocument.AFTER,
        )
        return None if raw is None else self.document_type.from_mongo(raw)

    async def delete(self, document_id: ObjectId | str) -> bool:
        """Delete one document by id; ``True`` when something was removed."""
        result = await self.collection.delete_one({"_id": ObjectId(document_id)})
        return result.deleted_count > 0

    async def delete_many(self, filter: Mapping[str, Any]) -> int:
        """Delete every document matching ``filter``; returns how many were removed."""
        result = await self.collection.delete_many(dict(filter))
        return result.deleted_count
