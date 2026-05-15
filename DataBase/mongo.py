from datetime import UTC, datetime

from pymongo import ASCENDING, AsyncMongoClient, ReturnDocument


class Database:
    def __init__(self, uri: str, db_name: str) -> None:
        self._uri = uri
        self._db_name = db_name
        self._client: AsyncMongoClient | None = None
        self._db = None

    async def connect(self) -> None:
        self._client = AsyncMongoClient(self._uri)
        self._db = self._client[self._db_name]
        await self._client.admin.command("ping")

    async def close(self) -> None:
        if self._client:
            await self._client.close()

    async def migrate(self) -> None:
        db = self._require_db()
        await db.users.create_index([("telegram_id", ASCENDING)], unique=True)
        await db.jobs.create_index([("user_id", ASCENDING), ("created_at", ASCENDING)])
        await db.jobs.create_index([("package_name", ASCENDING)])

        counters = db.counters
        await counters.update_one(
            {"_id": "jobs"},
            {"$setOnInsert": {"seq": 0}},
            upsert=True,
        )

    async def upsert_user(self, telegram_id: int, full_name: str) -> None:
        now = self._now()
        db = self._require_db()
        await db.users.update_one(
            {"telegram_id": telegram_id},
            {
                "$set": {
                    "full_name": full_name,
                    "updated_at": now,
                },
                "$setOnInsert": {
                    "telegram_id": telegram_id,
                    "created_at": now,
                },
            },
            upsert=True,
        )

    async def create_job(self, user_id: int, package_name: str, url: str) -> int:
        now = self._now()
        db = self._require_db()
        job_id = await self._next_job_id()
        await db.jobs.insert_one(
            {
                "_id": job_id,
                "user_id": user_id,
                "package_name": package_name,
                "url": url,
                "status": "created",
                "source_path": None,
                "apk_path": None,
                "error": None,
                "created_at": now,
                "updated_at": now,
            }
        )
        return job_id

    async def update_job(
        self,
        job_id: int,
        status: str,
        source_path: str | None = None,
        apk_path: str | None = None,
        error: str | None = None,
    ) -> None:
        db = self._require_db()
        updates = {
            "status": status,
            "error": error,
            "updated_at": self._now(),
        }
        if source_path is not None:
            updates["source_path"] = source_path
        if apk_path is not None:
            updates["apk_path"] = apk_path

        await db.jobs.update_one({"_id": job_id}, {"$set": updates})

    async def _next_job_id(self) -> int:
        db = self._require_db()
        counter = await db.counters.find_one_and_update(
            {"_id": "jobs"},
            {"$inc": {"seq": 1}},
            upsert=True,
            return_document=ReturnDocument.AFTER,
        )
        return int(counter["seq"])

    def _require_db(self):
        if self._db is None:
            raise RuntimeError("Database is not connected")
        return self._db

    @staticmethod
    def _now() -> datetime:
        return datetime.now(UTC)
