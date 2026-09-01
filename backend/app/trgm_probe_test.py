import pytest
from sqlalchemy import text


@pytest.mark.asyncio
async def test_candidates(session):
    for name in ["searcher", "quartermaster", "zebra", "admin"]:
        for term in ["three", "jordan", "morgan"]:
            value = (
                await session.exec(
                    text("SELECT word_similarity(:t, :n)").bindparams(t=term, n=name)
                )
            ).scalar_one()
            if value > 0:
                print(f"  {name!r} vs {term!r} = {value}")
        print(f"{name!r} checked")
