"""CLI для управления API-ключами.

Использование:
    .venv/bin/python -m catalog.cli create-key --owner parsers --scopes ingest
    .venv/bin/python -m catalog.cli list-keys
    .venv/bin/python -m catalog.cli revoke 5

Plaintext-ключ выводится один раз — при создании. Дальше в БД остаётся только
sha256-хеш; восстановить ключ нельзя, нужно сгенерировать новый и отозвать старый.
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import datetime, timezone

from sqlalchemy import select

from catalog.auth import generate_key, hash_key
from catalog.db import dispose_engine, get_engine
from catalog.models import ApiKey
from sqlalchemy.ext.asyncio import async_sessionmaker


async def _create_key(owner: str, scopes: list[str]) -> None:
    plaintext = generate_key()
    engine = get_engine()
    SessionFactory = async_sessionmaker(engine, expire_on_commit=False)
    async with SessionFactory() as session:
        api_key = ApiKey(key_hash=hash_key(plaintext), owner=owner, scopes=scopes)
        session.add(api_key)
        await session.commit()
        await session.refresh(api_key)
    await dispose_engine()
    print(f"id:     {api_key.id}")
    print(f"owner:  {owner}")
    print(f"scopes: {','.join(scopes)}")
    print()
    print("API key (показывается ОДИН РАЗ, сохраните в .env):")
    print(plaintext)


async def _list_keys() -> None:
    engine = get_engine()
    SessionFactory = async_sessionmaker(engine, expire_on_commit=False)
    async with SessionFactory() as session:
        keys = (
            await session.execute(select(ApiKey).order_by(ApiKey.id))
        ).scalars().all()
    await dispose_engine()
    if not keys:
        print("(no keys)")
        return
    print(f"{'id':<5}{'owner':<20}{'scopes':<30}{'created':<25}{'revoked':<25}")
    print("-" * 105)
    for k in keys:
        revoked = k.revoked_at.isoformat() if k.revoked_at else "-"
        scopes = ",".join(k.scopes or [])
        print(f"{k.id:<5}{k.owner:<20}{scopes:<30}{k.created_at.isoformat():<25}{revoked:<25}")


async def _revoke(key_id: int) -> None:
    engine = get_engine()
    SessionFactory = async_sessionmaker(engine, expire_on_commit=False)
    async with SessionFactory() as session:
        api_key = await session.get(ApiKey, key_id)
        if api_key is None:
            print(f"key {key_id} not found", file=sys.stderr)
            sys.exit(1)
        if api_key.revoked_at is not None:
            print(f"key {key_id} already revoked at {api_key.revoked_at}")
            return
        api_key.revoked_at = datetime.now(timezone.utc)
        await session.commit()
        print(f"revoked key {key_id} ({api_key.owner})")
    await dispose_engine()


def main() -> None:
    parser = argparse.ArgumentParser(prog="catalog.cli")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_create = sub.add_parser("create-key", help="Generate and store new API key")
    p_create.add_argument("--owner", required=True, help="e.g. parsers, web_test")
    p_create.add_argument(
        "--scopes",
        required=True,
        help="comma-separated: ingest,read,admin",
    )

    sub.add_parser("list-keys", help="List all keys with metadata")

    p_revoke = sub.add_parser("revoke", help="Revoke a key by id")
    p_revoke.add_argument("key_id", type=int)

    args = parser.parse_args()
    if args.cmd == "create-key":
        scopes = [s.strip() for s in args.scopes.split(",") if s.strip()]
        asyncio.run(_create_key(args.owner, scopes))
    elif args.cmd == "list-keys":
        asyncio.run(_list_keys())
    elif args.cmd == "revoke":
        asyncio.run(_revoke(args.key_id))


if __name__ == "__main__":
    main()
