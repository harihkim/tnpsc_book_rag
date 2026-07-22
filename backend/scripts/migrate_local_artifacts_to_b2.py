"""Script to migrate local disk artifacts (backend/artifacts/) to Backblaze B2 / S3 object storage."""

import asyncio
import sys
from pathlib import Path

from tnpsc_book_rag.config import Settings
from tnpsc_book_rag.artifact_storage import ArtifactKey, S3ArtifactStorage, create_artifact_storage


async def main() -> None:
    settings = Settings()
    if settings.storage_backend != "s3":
        print("Error: TNPSC_STORAGE_BACKEND must be set to 's3' to run migration.")
        print("Ensure S3 environment variables (TNPSC_S3_ENDPOINT_URL, TNPSC_S3_BUCKET, TNPSC_S3_ACCESS_KEY_ID, TNPSC_S3_SECRET_ACCESS_KEY) are configured.")
        sys.exit(1)

    storage = create_artifact_storage(settings)
    if not isinstance(storage, S3ArtifactStorage):
        print("Error: Configured storage adapter is not S3ArtifactStorage.")
        sys.exit(1)

    print(f"Initializing connection to bucket '{settings.s3_bucket}'...")
    await storage.initialize()
    print("Bucket access verified.")

    local_root = settings.artifact_root.expanduser().resolve()
    if not local_root.exists() or not local_root.is_dir():
        print(f"No local artifact directory found at '{local_root}'. Nothing to migrate.")
        return

    files_to_migrate = [p for p in local_root.rglob("*") if p.is_file()]
    print(f"Found {len(files_to_migrate)} local artifact files in '{local_root}'.")

    migrated_count = 0
    skipped_count = 0
    total_bytes = 0

    for file_path in files_to_migrate:
        rel_path = file_path.relative_to(local_root).as_posix()
        try:
            key = ArtifactKey(rel_path)
        except Exception as exc:
            print(f"Skipping invalid key '{rel_path}': {exc}")
            skipped_count += 1
            continue

        size = file_path.stat().st_size
        total_bytes += size
        with open(file_path, "rb") as fp:
            result = await storage.put(key, fp)
            if result.created:
                print(f"Uploaded: {key.value} ({size} bytes)")
                migrated_count += 1
            else:
                print(f"Already exists (skipped): {key.value}")
                skipped_count += 1

    print(f"\nMigration finished: {migrated_count} uploaded, {skipped_count} skipped/existing, total {total_bytes / (1024*1024):.2f} MB processed.")


if __name__ == "__main__":
    asyncio.run(main())
