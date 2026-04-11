"""
基于当前 Organizer 规则输出构造弱监督训练集。
"""
import argparse
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.database import get_db_context  # noqa: E402
from app.models import UserSession  # noqa: E402
from app.services.video_organizer import VideoOrganizerService  # noqa: E402
from app.services.video_classifier import OrganizerVideoSample, build_video_classifier_features  # noqa: E402
from sqlalchemy import select  # noqa: E402


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default=str(ROOT / "data" / "training" / "organizer_classifier.jsonl"))
    parser.add_argument("--session-id", default=None, help="指定 session_id；为空时导出全部 session")
    args = parser.parse_args()

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    rows_out = 0
    async with get_db_context() as db:
        session_ids: list[str]
        if args.session_id:
            session_ids = [args.session_id]
        else:
            result = await db.execute(select(UserSession.session_id).where(UserSession.is_valid == True))  # noqa: E712
            session_ids = [row[0] for row in result.all()]

        with output_path.open("w", encoding="utf-8") as handle:
            for session_id in session_ids:
                service = VideoOrganizerService(db)
                report = await service.build_report(session_id=session_id)
                for video in report["videos"]:
                    if video["confidence"] < 0.55:
                        continue
                    sample = OrganizerVideoSample(
                        title=video["title"],
                        description="",
                        summary="",
                        folder_titles=video["folder_titles"],
                        tags=video["subject_tags"],
                        knowledge_node_count=video["knowledge_node_count"],
                        claim_count=video["claim_count"],
                        segment_count=video["segment_count"],
                        avg_node_difficulty=1.0 if video["difficulty_level"] == "入门" else 3.0 if video["difficulty_level"] == "进阶" else 5.0,
                        node_confidence_avg=video["confidence"],
                        duration=video["duration"] or 0,
                    )
                    numeric, tokens = build_video_classifier_features(sample)
                    row = {
                        "numeric_features": numeric,
                        "token_features": tokens,
                        "labels": {
                            "primary_subject": video["subject_tags"][0] if video["subject_tags"] else "未分类",
                            "content_type": video["content_type"],
                            "difficulty_level": video["difficulty_level"],
                            "value_tier": video["value_tier"],
                        },
                    }
                    handle.write(json.dumps(row, ensure_ascii=False) + "\n")
                    rows_out += 1

    print(f"Wrote {rows_out} rows to {output_path}")


if __name__ == "__main__":
    asyncio.run(main())
