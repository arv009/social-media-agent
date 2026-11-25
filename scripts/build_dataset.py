"""Build data/processed/posts.csv from every available source.

    python scripts/build_dataset.py              # sample data + any CSVs in data/raw
    python scripts/build_dataset.py --meta       # also fetch from the Meta API (.env needed)
    python scripts/build_dataset.py --no-sample  # real data only

Once you have enough real posts (about 100+), run with --no-sample so the
model learns from your account only.
"""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from dotenv import load_dotenv  # noqa: E402

from social_agent import synthetic  # noqa: E402
from social_agent.loaders import MetaClient, load_folder  # noqa: E402
from social_agent.schema import combine  # noqa: E402


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--meta", action="store_true", help="fetch from the Meta Graph API")
    parser.add_argument("--no-sample", action="store_true", help="leave out the synthetic sample data")
    parser.add_argument("--max-posts", type=int, default=200)
    args = parser.parse_args()
    load_dotenv(ROOT / ".env")

    frames = []
    if not args.no_sample:
        sample_path = ROOT / "data/sample/posts_sample.csv"
        sample = synthetic.generate()
        sample.to_csv(sample_path, index=False)
        frames.append(sample)
        print(f"sample data:  {len(sample)} posts -> {sample_path.relative_to(ROOT)}")

    raw = load_folder(ROOT / "data/raw")
    if not raw.empty:
        frames.append(raw)
        print(f"CSV exports:  {len(raw)} posts from data/raw/")

    if args.meta:
        client = MetaClient()
        meta = client.fetch_all(args.max_posts)
        if not meta.empty:
            meta.to_csv(ROOT / "data/processed/meta_api_latest.csv", index=False)
            frames.append(meta)
        print(f"Meta API:     {len(meta)} posts")
        if client.skipped_metrics:
            print(f"  (skipped metrics Meta no longer supports: {sorted(client.skipped_metrics)})")

    if not frames:
        sys.exit("No data found. Add exports to data/raw/ or drop --no-sample.")
    df = combine(*frames)
    out = ROOT / "data/processed/posts.csv"
    df.to_csv(out, index=False)
    print(f"combined:     {len(df)} posts -> {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
